"""Space-Track ingestion: keeps databases/ingestionSpaceTrack.db holding
what Space-Track -- the 18th Space Defense Squadron's publication of the
NORAD catalogue -- currently says about every object in orbit.

Step 5 of 0_documentation/dbRefactorPlan.md. Space-Track is the primary
orbital source (decision: the source closest to NORAD wins). This script
only fetches and stores; it never decides what the website shows -- the
publish step (publishSite.py, step 9) merges this with the other
ingestion databases into siteOrbital.db.

Two kinds of pass, chosen automatically (override with --full/--recent):

  full    once a day: the whole current catalogue -- every object not
          decayed with an element set from the last 30 days (Space-Track's
          own recommended catalogue query), plus every object that decayed
          in the last 30 days. Marks each object it returns as seen in
          this pass (lastSeenFull), so the publish step can tell objects
          still in the catalogue from ones that have dropped out of it.
  recent  otherwise (cron runs this twice a day): element sets with an
          epoch in the last 2 days -- the objects that moved since.

Space-Track asks for no more than one full-catalogue GP query an hour;
the full pass runs once a day. One login per pass, logged out after.

Storage: table gp, one row per NORAD ID, Space-Track's GP fields as they
arrive (numbers converted from Space-Track's strings, names converted
to this project's camelCase), plus fetchedAt. The TLE_LINE0-2 text is
not kept: the OMM fields carry the same elements, without the 5-digit
catalogue-number limit. A row is only replaced by an element set with
a later epoch -- or the same epoch with changed metadata, such as a new
decay date -- so an out-of-order response can never move an object
backwards, and a repeated record is not counted as a change.

Every run is recorded in the database's ingestionRuns table (jobs
spaceTrackFull / spaceTrackRecent), failed runs as failed.
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

from common import SpaceTrack
from dbPaths import SPACETRACK_DB, dbPath
from ingestionLog import trackRun, utcNowIso

# (Space-Track GP field, our column, SQLite type). Order is the table's
# column order.
GP_FIELDS = (
    ('NORAD_CAT_ID', 'noradID', 'INTEGER'),
    ('OBJECT_NAME', 'objectName', 'TEXT'),
    ('OBJECT_ID', 'objectID', 'TEXT'),
    ('OBJECT_TYPE', 'objectType', 'TEXT'),
    ('EPOCH', 'epoch', 'TEXT'),
    ('MEAN_MOTION', 'meanMotion', 'REAL'),
    ('ECCENTRICITY', 'eccentricity', 'REAL'),
    ('INCLINATION', 'inclination', 'REAL'),
    ('RA_OF_ASC_NODE', 'raOfAscNode', 'REAL'),
    ('ARG_OF_PERICENTER', 'argOfPericenter', 'REAL'),
    ('MEAN_ANOMALY', 'meanAnomaly', 'REAL'),
    ('BSTAR', 'bstar', 'REAL'),
    ('MEAN_MOTION_DOT', 'meanMotionDot', 'REAL'),
    ('MEAN_MOTION_DDOT', 'meanMotionDdot', 'REAL'),
    ('SEMIMAJOR_AXIS', 'semimajorAxis', 'REAL'),
    ('PERIOD', 'period', 'REAL'),
    ('APOAPSIS', 'apoapsis', 'REAL'),
    ('PERIAPSIS', 'periapsis', 'REAL'),
    ('REV_AT_EPOCH', 'revAtEpoch', 'INTEGER'),
    ('ELEMENT_SET_NO', 'elementSetNo', 'INTEGER'),
    ('EPHEMERIS_TYPE', 'ephemerisType', 'INTEGER'),
    ('CLASSIFICATION_TYPE', 'classificationType', 'TEXT'),
    ('RCS_SIZE', 'rcsSize', 'TEXT'),
    ('COUNTRY_CODE', 'countryCode', 'TEXT'),
    ('LAUNCH_DATE', 'launchDate', 'TEXT'),
    ('SITE', 'site', 'TEXT'),
    ('DECAY_DATE', 'decayDate', 'TEXT'),
    ('CREATION_DATE', 'creationDate', 'TEXT'),
    ('ORIGINATOR', 'originator', 'TEXT'),
    ('CENTER_NAME', 'centerName', 'TEXT'),
    ('REF_FRAME', 'refFrame', 'TEXT'),
    ('TIME_SYSTEM', 'timeSystem', 'TEXT'),
    ('MEAN_ELEMENT_THEORY', 'meanElementTheory', 'TEXT'),
    ('CCSDS_OMM_VERS', 'ccsdsOmmVers', 'TEXT'),
    ('FILE', 'file', 'INTEGER'),
    ('GP_ID', 'gpID', 'INTEGER'),
)
COLUMNS = [column for _, column, _ in GP_FIELDS]

QUERY_ROOT = '/basicspacedata/query/class/gp'
# Space-Track's recommended current-catalogue query.
FULL_CATALOGUE_QUERY = f'{QUERY_ROOT}/decay_date/null-val/epoch/%3Enow-30/orderby/norad_cat_id/format/json'
RECENT_DECAYS_QUERY = f'{QUERY_ROOT}/decay_date/%3Enow-30/orderby/norad_cat_id/format/json'
RECENT_ELEMENTS_QUERY = f'{QUERY_ROOT}/epoch/%3Enow-2/orderby/norad_cat_id/format/json'

# A full pass is due when the last successful one finished longer ago
# than this. 23 h rather than 24, so a twice-daily cron run a little
# early still counts.
FULL_INTERVAL = timedelta(hours=23)

FULL_JOB = 'spaceTrackFull'
RECENT_JOB = 'spaceTrackRecent'


def openDb(path=None):
    db = sqlite3.connect(path or dbPath(SPACETRACK_DB))
    db.execute('PRAGMA journal_mode = WAL')
    ensureSchema(db)
    return db


def ensureSchema(db):
    columns = ',\n        '.join(
        f'{column} {kind}' + (' PRIMARY KEY' if column == 'noradID' else '')
        for _, column, kind in GP_FIELDS)
    db.execute(f'''
        CREATE TABLE IF NOT EXISTS gp (
            {columns},
            fetchedAt    TEXT NOT NULL,
            lastSeenFull TEXT
        )''')
    db.execute('CREATE INDEX IF NOT EXISTS gpByEpoch ON gp (epoch)')
    db.commit()


def toValue(raw, kind):
    if raw is None or raw == '':
        return None
    try:
        if kind == 'INTEGER':
            return int(raw)
        if kind == 'REAL':
            return float(raw)
    except (TypeError, ValueError):
        return None
    return str(raw)


def rowFromGp(entry):
    """Our column values for one Space-Track GP record, or None when it
    lacks a NORAD ID or epoch (nothing to key or order it by)."""
    row = {column: toValue(entry.get(field), kind) for field, column, kind in GP_FIELDS}
    if row['noradID'] is None or not row['epoch']:
        return None
    return row


# With an equal epoch, a record only replaces the stored one when one of
# these differs (Space-Track can add a decay date or correct metadata
# without a new element set). Otherwise it is the same record again and
# doesn't count as a change -- which matters, because a change is what
# triggers a publish (plan decision C1).
SAME_EPOCH_CHANGES = ('gpID', 'decayDate', 'objectType', 'objectName', 'objectID', 'countryCode',
                      'rcsSize', 'launchDate', 'site')

UPSERT_SQL = f'''
    INSERT INTO gp ({', '.join(COLUMNS)}, fetchedAt, lastSeenFull)
    VALUES ({', '.join('?' * len(COLUMNS))}, ?, ?)
    ON CONFLICT(noradID) DO UPDATE SET
        {', '.join(f'{c} = excluded.{c}' for c in COLUMNS if c != 'noradID')},
        fetchedAt = excluded.fetchedAt,
        lastSeenFull = COALESCE(excluded.lastSeenFull, gp.lastSeenFull)
    WHERE excluded.epoch > gp.epoch
       OR (excluded.epoch = gp.epoch AND ({' OR '.join(f'excluded.{c} IS NOT gp.{c}' for c in SAME_EPOCH_CHANGES)}))
'''
# A full pass also marks objects whose stored element set is newer than
# the one returned (so the upsert above skipped them) as still seen.
MARK_SEEN_SQL = 'UPDATE gp SET lastSeenFull = ? WHERE noradID = ? AND (lastSeenFull IS NULL OR lastSeenFull < ?)'


def storeEntries(db, entries, fetchedAt, seenFull=None):
    """Upserts GP records in one transaction. seenFull: the full pass's
    timestamp, recorded as lastSeenFull on every object returned.
    Returns the number of rows inserted or changed."""
    changed = 0
    with db:
        for entry in entries:
            row = rowFromGp(entry)
            if row is None:
                continue
            cursor = db.execute(UPSERT_SQL, [row[c] for c in COLUMNS] + [fetchedAt, seenFull])
            changed += cursor.rowcount
            if seenFull:
                db.execute(MARK_SEEN_SQL, (seenFull, row['noradID'], seenFull))
    return changed


def lastSuccessfulFull(db):
    try:
        row = db.execute('SELECT MAX(finishedAt) FROM ingestionRuns WHERE job = ? AND succeeded = 1',
                         (FULL_JOB,)).fetchone()
    except sqlite3.OperationalError:  # no runs recorded yet
        return None
    if not row or not row[0]:
        return None
    return datetime.strptime(row[0], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def fullPassDue(db, now=None):
    last = lastSuccessfulFull(db)
    now = now or datetime.now(timezone.utc)
    return last is None or now - last >= FULL_INTERVAL


def fetchJson(spaceTrack, query):
    status, text = spaceTrack.get(query)
    if status >= 400:
        raise Exception(f'Space-Track query failed: HTTP {status}')
    data = json.loads(text)
    if not isinstance(data, list):
        raise Exception(f'Space-Track returned {type(data).__name__}, not a list')
    return data


def runPass(db, spaceTrack, full):
    """One pass. Returns (rows changed, note)."""
    fetchedAt = utcNowIso()
    with spaceTrack:
        if full:
            catalogue = fetchJson(spaceTrack, FULL_CATALOGUE_QUERY)
            decays = fetchJson(spaceTrack, RECENT_DECAYS_QUERY)
        else:
            recent = fetchJson(spaceTrack, RECENT_ELEMENTS_QUERY)
    if full:
        # An empty catalogue means something went wrong upstream; storing
        # it would mark nothing seen and drop every object at publish.
        if not catalogue:
            raise Exception('Space-Track returned an empty catalogue')
        previousFull = db.execute('SELECT MAX(lastSeenFull) FROM gp').fetchone()[0]
        changed = storeEntries(db, catalogue, fetchedAt, seenFull=fetchedAt)
        changed += storeEntries(db, decays, fetchedAt)
        # Objects in the previous full pass but not this one have left the
        # catalogue. No row changes for them, but the site must drop them,
        # so they count as changes (a change triggers a publish).
        droppedOut = db.execute('SELECT COUNT(*) FROM gp WHERE lastSeenFull = ?',
                                (previousFull,)).fetchone()[0] if previousFull else 0
        return changed + droppedOut, (f'{len(catalogue)} in catalogue, {len(decays)} recent decays, '
                                      f'{droppedOut} left the catalogue')
    changed = storeEntries(db, recent, fetchedAt)
    return changed, f'{len(recent)} recent element sets'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Space-Track ingestion into ingestionSpaceTrack.db.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--full', action='store_true', help='force a full-catalogue pass')
    mode.add_argument('--recent', action='store_true', help='force a recent-elements pass')
    args = parser.parse_args(argv)

    db = openDb()
    full = args.full or (not args.recent and fullPassDue(db))
    job = FULL_JOB if full else RECENT_JOB
    spaceTrack = SpaceTrack()
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Space-Track {"full" if full else "recent"} pass ===')
    with trackRun(db, job) as run:
        if not spaceTrack.configured:
            run.failed, run.note = True, 'no Space-Track credentials configured'
        else:
            try:
                run.changes, run.note = runPass(db, spaceTrack, full)
            except Exception as error:
                run.failed, run.note = True, f'{type(error).__name__}: {error}'[:500]
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes or 0} rows changed')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
