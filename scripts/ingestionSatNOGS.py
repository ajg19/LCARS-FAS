"""SatNOGS ingestion: keeps databases/ingestionSatNOGS.db holding the
SatNOGS DB's (db.satnogs.org, crowd-sourced, CC BY-SA) radio transmitter
records, and the crosswalk from SatNOGS's own satellite numbers to
NORAD's.

Step 7 of 0_documentation/dbRefactorPlan.md. One script for both SatNOGS
feeds, which used to be read by ingestOrbitalData.py (TLEs) and
ingestSatnogsRf.py (transmitters). It only fetches and stores; the
publish step (step 9) decides what reaches the website.

Why the TLE feed is kept, and why it supplies no orbits (decided
2026-10-21). SatNOGS only publishes TLE text, never OMM, and doesn't
support Alpha-5, so since NORAD's 5-digit catalogue numbers ran out in
July 2026 it can't carry a new satellite's real number. A newly launched
satellite appears under a SatNOGS placeholder number (98xxx / 99xxx),
usually with Space-Track's elements for the real object re-encoded under
that number; most of the rest of the feed is plain copies of Space-Track
TLEs. Orbits therefore come from Space-Track alone. But the transmitter
records -- the link budget's real frequencies -- are filed under
SatNOGS's numbers, and for satellites launched since July neither
norad_follow_id nor the satellites endpoint links a placeholder to
NORAD's object. The international designator in the TLE line does (e.g.
SatNOGS 98193 carries 2026-229K), so the feed is kept as that crosswalk.
The publish step links each transmitter to a NORAD object by, in order:
  1. its norad_follow_id;
  2. the designator from SatNOGS's TLE for its norad_cat_id, matched to
     Space-Track's OBJECT_ID;
  3. its norad_cat_id.

Feeds -- one unauthenticated GET each, the whole set every time:
  tle           ~1.7k records. tle_source says where SatNOGS got each one.
  transmitters  ~5k records, one per transmitter / transceiver /
                transponder.

Storage:
  tle           the crosswalk, one row per SatNOGS number (noradID): the
                catalogue number and international designator from the
                TLE line, the name, source, epoch and raw TLE lines,
                fetchedAt and lastSeen (the last fetch that listed it).
                No orbital elements are decoded. A row is only replaced
                by a later epoch, or the same epoch with a changed TLE,
                source or name.
  transmitters  one row per record (keyed by SatNOGS's uuid), replaced
                wholesale on every successful fetch. Picking each
                satellite's main downlink / uplink (choose_rf in
                ingestSatnogsRf.py) is publish work, so every record is
                kept as SatNOGS gives it.

"changes" -- what triggers a publish (decision C1) -- counts crosswalk
rows inserted or replaced, rows that left the TLE feed, and transmitter
records added, removed or updated. A feed that fails leaves its table
as it was; the run is then recorded as failed.
"""

import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

from common import httpGet
from dbPaths import SATNOGS_DB, dbPath
from ingestionLog import trackRun, utcNowIso

TLE_URL = 'https://db.satnogs.org/api/tle/?format=json'
TRANSMITTERS_URL = 'https://db.satnogs.org/api/transmitters/?format=json'
JOB = 'satnogs'

# (SatNOGS field, our column, SQLite type) for transmitter records.
# itu_notification and params are JSON objects, stored as JSON text.
TX_FIELDS = (
    ('uuid', 'uuid', 'TEXT'),
    ('norad_cat_id', 'noradID', 'INTEGER'),
    ('norad_follow_id', 'noradFollowID', 'INTEGER'),
    ('sat_id', 'satID', 'TEXT'),
    ('description', 'description', 'TEXT'),
    ('alive', 'alive', 'INTEGER'),
    ('type', 'type', 'TEXT'),
    ('status', 'status', 'TEXT'),
    ('uplink_low', 'uplinkLow', 'REAL'),
    ('uplink_high', 'uplinkHigh', 'REAL'),
    ('uplink_drift', 'uplinkDrift', 'REAL'),
    ('uplink_drifted', 'uplinkDrifted', 'REAL'),
    ('uplink_mode', 'uplinkMode', 'TEXT'),
    ('downlink_low', 'downlinkLow', 'REAL'),
    ('downlink_high', 'downlinkHigh', 'REAL'),
    ('downlink_drift', 'downlinkDrift', 'REAL'),
    ('downlink_drifted', 'downlinkDrifted', 'REAL'),
    ('mode', 'mode', 'TEXT'),
    ('mode_id', 'modeID', 'INTEGER'),
    ('invert', 'invert', 'INTEGER'),
    ('baud', 'baud', 'REAL'),
    ('service', 'service', 'TEXT'),
    ('frequency_violation', 'frequencyViolation', 'INTEGER'),
    ('unconfirmed', 'unconfirmed', 'INTEGER'),
    ('iaru_coordination', 'iaruCoordination', 'TEXT'),
    ('iaru_coordination_url', 'iaruCoordinationUrl', 'TEXT'),
    ('itu_notification', 'ituNotification', 'JSON'),
    ('params', 'params', 'JSON'),
    ('citation', 'citation', 'TEXT'),
    ('updated', 'updated', 'TEXT'),
)
TX_COLUMNS = [column for _, column, _ in TX_FIELDS]

TLE_COLUMNS = ('noradID', 'tleCatalogNumber', 'designator', 'objectName', 'tleSource', 'satID', 'updated',
               'epoch', 'tle0', 'tle1', 'tle2')


def openDb(path=None):
    db = sqlite3.connect(path or dbPath(SATNOGS_DB))
    db.execute('PRAGMA journal_mode = WAL')
    tx = ',\n            '.join(f'{column} {"TEXT" if kind == "JSON" else kind}'
                                + (' PRIMARY KEY' if column == 'uuid' else '')
                                for _, column, kind in TX_FIELDS)
    db.executescript(f'''
        CREATE TABLE IF NOT EXISTS tle (
            noradID          INTEGER PRIMARY KEY,
            tleCatalogNumber INTEGER,
            designator       TEXT,
            objectName       TEXT,
            tleSource        TEXT,
            satID            TEXT,
            updated          TEXT,
            epoch            TEXT NOT NULL,
            tle0             TEXT,
            tle1             TEXT NOT NULL,
            tle2             TEXT NOT NULL,
            fetchedAt        TEXT NOT NULL,
            lastSeen         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS tleByDesignator ON tle (designator);
        CREATE TABLE IF NOT EXISTS transmitters (
            {tx}
        );
        CREATE INDEX IF NOT EXISTS transmittersByNorad ON transmitters (noradID);
    ''')
    db.commit()
    return db


# --- TLE crosswalk fields -----------------------------------------------------
# Line 1 columns (TLE spec): 3-7 catalogue number, 10-17 international
# designator (YYNNNPPP), 19-32 epoch.

def tleEpoch(line1):
    """ISO epoch from TLE line 1, in Space-Track's format
    (YYYY-MM-DDTHH:MM:SS.ffffff, UTC, no zone suffix)."""
    field = line1[18:32].strip()
    year = int(field[:2])
    year += 2000 if year < 57 else 1900
    epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=float(field[2:]) - 1)
    return epoch.strftime('%Y-%m-%dT%H:%M:%S.%f')


def tleDesignator(line1):
    """'26229K  ' -> '2026-229K', Space-Track's OBJECT_ID form; None when
    the field is blank or malformed (some team-supplied TLEs leave it
    empty)."""
    field = line1[9:17].strip()
    if len(field) < 6 or not field[:5].isdigit():
        return None
    year = int(field[:2])
    return f'{2000 + year if year < 57 else 1900 + year}-{field[2:]}'


def tleCatalogNumber(line1):
    """The catalogue number in TLE line 1 -- for a SatNOGS placeholder
    the placeholder itself. None if not plain digits (Alpha-5)."""
    field = line1[2:7].strip()
    return int(field) if field.isdigit() else None


def tleRow(record):
    """Crosswalk values for one SatNOGS TLE record, or None when it lacks
    a NORAD ID or its line 1 has no readable epoch."""
    norad = record.get('norad_cat_id')
    line1, line2 = record.get('tle1') or '', record.get('tle2') or ''
    if not isinstance(norad, int) or isinstance(norad, bool) or norad <= 0 or not line2:
        return None
    try:
        epoch = tleEpoch(line1)
    except (ValueError, IndexError):
        return None
    tle0 = (record.get('tle0') or '').strip()
    return {
        'noradID': norad,
        'tleCatalogNumber': tleCatalogNumber(line1),
        'designator': tleDesignator(line1),
        'objectName': tle0[2:].strip() if tle0.startswith('0 ') else tle0,
        'tleSource': record.get('tle_source'), 'satID': record.get('sat_id'),
        'updated': record.get('updated'), 'epoch': epoch,
        'tle0': tle0 or None, 'tle1': line1, 'tle2': line2,
    }


UPSERT_TLE_SQL = f'''
    INSERT INTO tle ({', '.join(TLE_COLUMNS)}, fetchedAt, lastSeen)
    VALUES ({', '.join('?' * len(TLE_COLUMNS))}, ?, ?)
    ON CONFLICT(noradID) DO UPDATE SET
        {', '.join(f'{c} = excluded.{c}' for c in TLE_COLUMNS if c != 'noradID')},
        fetchedAt = excluded.fetchedAt
    WHERE excluded.epoch > tle.epoch
       OR (excluded.epoch = tle.epoch AND (excluded.tle1 IS NOT tle.tle1 OR excluded.tle2 IS NOT tle.tle2
                                           OR excluded.tleSource IS NOT tle.tleSource
                                           OR excluded.objectName IS NOT tle.objectName))
'''


def storeTles(db, records, now):
    """Upserts the TLE feed in one transaction and marks every object it
    lists as seen. Returns (changes, stored, skipped): changes includes
    objects that were in the previous fetch but not this one."""
    changes = stored = skipped = 0
    with db:
        previous = db.execute('SELECT MAX(lastSeen) FROM tle').fetchone()[0]
        for record in records:
            row = tleRow(record)
            if row is None:
                skipped += 1
                continue
            cursor = db.execute(UPSERT_TLE_SQL, [row[c] for c in TLE_COLUMNS] + [now, now])
            changes += cursor.rowcount
            db.execute('UPDATE tle SET lastSeen = ? WHERE noradID = ?', (now, row['noradID']))
            stored += 1
        if previous:
            changes += db.execute('SELECT COUNT(*) FROM tle WHERE lastSeen = ?', (previous,)).fetchone()[0]
    return changes, stored, skipped


# --- Transmitters -----------------------------------------------------------

def txValue(raw, kind):
    if raw is None or raw == '':
        return None
    if kind == 'JSON':
        return json.dumps(raw, sort_keys=True)
    if kind in ('INTEGER', 'REAL'):
        if isinstance(raw, bool):
            return int(raw)
        try:
            return int(raw) if kind == 'INTEGER' else float(raw)
        except (TypeError, ValueError):
            return None
    return str(raw)


def txRow(record):
    row = {column: txValue(record.get(field), kind) for field, column, kind in TX_FIELDS}
    return row if row['uuid'] else None


def storeTransmitters(db, records):
    """Replaces the transmitters table in one transaction. Returns
    (changes, stored): records added, removed, or with a new 'updated'."""
    rows = [r for r in (txRow(record) for record in records) if r]
    with db:
        old = dict(db.execute('SELECT uuid, updated FROM transmitters'))
        new = {r['uuid']: r['updated'] for r in rows}
        db.execute('DELETE FROM transmitters')
        db.executemany(f'INSERT OR REPLACE INTO transmitters ({", ".join(TX_COLUMNS)}) '
                       f'VALUES ({", ".join("?" * len(TX_COLUMNS))})',
                       [[r[c] for c in TX_COLUMNS] for r in rows])
    changes = len(new.keys() ^ old.keys()) + sum(1 for u in new.keys() & old.keys() if new[u] != old[u])
    return changes, len(rows)


# --- Run ----------------------------------------------------------------------

def fetchList(url):
    status, text = httpGet(url, {'Accept': 'application/json'})
    if status >= 400:
        raise Exception(f'HTTP {status}')
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get('results', [])
    if not data:
        raise Exception('empty response')
    return data


def runIngestion(db, fetch=fetchList):
    """Both feeds, each independent of the other's failure. Returns
    (changes, failed, note)."""
    changes, failures, notes = 0, [], []
    now = utcNowIso()
    for name, url in (('tle', TLE_URL), ('transmitters', TRANSMITTERS_URL)):
        try:
            records = fetch(url)
            if name == 'tle':
                changed, stored, skipped = storeTles(db, records, now)
                notes.append(f'{stored} crosswalk TLEs' + (f' ({skipped} unreadable)' if skipped else ''))
            else:
                changed, stored = storeTransmitters(db, records)
                notes.append(f'{stored} transmitters')
            changes += changed
            print(f'  {name}: {stored} stored, {changed} changed')
        except Exception as error:
            failures.append(f'{name}: {type(error).__name__}: {error}')
            print(f'  {name}: ERROR {error} -- table left as it was')
    note = ', '.join(notes) + ('; FAILED ' + '; '.join(failures) if failures else '')
    return changes, bool(failures), note[:500]


def main():
    db = openDb()
    print(f'\n=== [{time.strftime("%H:%M:%S")}] SatNOGS ingestion ===')
    with trackRun(db, JOB) as run:
        run.changes, run.failed, run.note = runIngestion(db)
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} changes')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
