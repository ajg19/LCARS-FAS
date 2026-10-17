"""Server side script enriching the orbital object cache with catalogue
metadata (object type, owner, launch date, decay date, radar cross-
section) that ingestOrbitalData.py deliberately never writes.

Python port of ingestSatcat.js -- second of the two separate processes,
kept apart from the TLE job so a stall in one can't take out the other,
run on a much slower (once-daily) cadence since this metadata changes far
less often than orbital elements do.

Request budget per run, by design: ONE unauthenticated GET (CelesTrak's
satcat.csv, a single pre-built bulk file) plus, if configured, ONE
Space-Track login POST and ONE authenticated GET. No loops, no per-object
or per-group requests.
"""

import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

# The DB and .env live in the repo root; this script sits in scripts/, one level down.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Minimal stdlib .env loader -- see ingestOrbitalData.py for the same
# helper; duplicated rather than shared, matching this project's own
# no-shared-module convention between its ingestion scripts.
def load_dotenv(path):
    if not os.path.isfile(path):
        return
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip())


load_dotenv(os.path.join(BASE_DIR, '.env'))
# Space-Track credentials live in spacetrack.env (chmod 600, never deployed
# or committed), read here rather than passed on the cron line.
load_dotenv(os.path.join(BASE_DIR, 'spacetrack.env'))

# 1. Connect to the SAME database ingestOrbitalData.py writes to -- this
# job enriches existing rows, it doesn't own a database of its own.
# isolation_level=None (autocommit) matches node:sqlite's DatabaseSync
# behaviour -- see ingestOrbitalData.py for the same reasoning.
db_path = os.path.join(BASE_DIR, 'ingestionDBs', 'orbitalObjects.db')
db = sqlite3.connect(db_path, isolation_level=None)
db.execute('PRAGMA journal_mode = WAL;')

# Schema kept identical to ingestOrbitalData.py and idempotent (IF NOT
# EXISTS) so either script can run first without caring which one does.
# TLE line1/line2 have been replaced by OMM element columns -- see
# ingestOrbitalData.py's module docstring for why; this script never
# populated those columns itself, but mirrors the schema since both
# scripts connect to the same DB file.
db.execute('''
    CREATE TABLE IF NOT EXISTS orbital_objects (
        noradID          INTEGER PRIMARY KEY,
        name             TEXT,
        objectID         TEXT,
        epoch            TEXT,
        meanMotion       REAL,
        eccentricity     REAL,
        inclination      REAL,
        raOfAscNode      REAL,
        argOfPericenter  REAL,
        meanAnomaly      REAL,
        bstar            REAL,
        meanMotionDot    REAL,
        meanMotionDdot   REAL,
        objectType       TEXT,
        owner            TEXT,
        launchDate       TEXT,
        launchSite       TEXT,
        decayDate        TEXT,
        rcsSize          REAL,
        period           REAL,
        apogee           REAL,
        perigee          REAL,
        source           TEXT,
        fetchedAt        DATETIME DEFAULT CURRENT_TIMESTAMP
    );
''')

# See the matching migration in ingestOrbitalData.py -- kept here too
# since either script can be the first one to run against a fresh (or
# pre-existing, pre-migration) database.
NEW_COLUMNS = (
    'period REAL', 'apogee REAL', 'perigee REAL',
    'objectID TEXT', 'meanMotion REAL', 'eccentricity REAL', 'inclination REAL',
    'raOfAscNode REAL', 'argOfPericenter REAL', 'meanAnomaly REAL', 'bstar REAL',
    'meanMotionDot REAL', 'meanMotionDdot REAL', 'launchSite TEXT',
)
for column in NEW_COLUMNS:
    try:
        db.execute(f'ALTER TABLE orbital_objects ADD COLUMN {column};')
    except sqlite3.OperationalError as err:
        if 'duplicate column name' not in str(err).lower():
            raise

for column in ('line1', 'line2'):
    try:
        db.execute(f'ALTER TABLE orbital_objects DROP COLUMN {column};')
    except sqlite3.OperationalError as err:
        message = str(err).lower()
        if 'no such column' not in message and 'syntax error' not in message:
            raise

# 2. Update statements -- deliberately plain UPDATEs, not upserts. Only
# objects ingestOrbitalData.py has already created a row for get enriched;
# a no-op UPDATE against a missing noradID is silent and harmless, which
# is exactly the behaviour wanted here (CelesTrak's satcat.csv goes back
# to Sputnik 1 -- blindly upserting every row would flood the table with
# tens of thousands of long-dead objects never part of this table's
# "current + recently-decayed" dataset).
#
# rcsSize is only ever set from CelesTrak: its RCS column is a genuine
# numeric radar cross-section in square metres, matching the REAL column
# type. Space-Track's equivalent (RCS_SIZE) is a coarse SMALL/MEDIUM/
# LARGE category, not a number -- the Space-Track backfill pass below
# leaves rcsSize alone entirely rather than coercing a category into it.
UPDATE_FROM_CELESTRAK_SQL = '''
    UPDATE orbital_objects
    SET objectType = ?, owner = ?, launchDate = ?, launchSite = ?, decayDate = ?, rcsSize = ?,
        period = ?, apogee = ?, perigee = ?
    WHERE noradID = ?
'''
UPDATE_FROM_SPACETRACK_SQL = '''
    UPDATE orbital_objects
    SET objectType = ?, owner = ?, launchDate = ?, launchSite = ?, decayDate = ?,
        period = ?, apogee = ?, perigee = ?
    WHERE noradID = ?
'''


# Object types are stored as CelesTrak's short codes -- PAY, R/B, DEB, UNK --
# whichever source a row came from: every reader (server.py's catalogue
# queries, enrichEirp.py, orbitStats.py, the GRD-TRACK search) filters on
# them. Space-Track spells the same types out in full; mapped here. Without
# this, a server where CelesTrak is unreachable (GoDaddy, October 2026) ends
# up with a catalogue of PAYLOAD / ROCKET BODY / DEBRIS that nothing matches.
SPACETRACK_OBJECT_TYPES = {
    'PAYLOAD': 'PAY',
    'ROCKET BODY': 'R/B',
    'DEBRIS': 'DEB',
    'UNKNOWN': 'UNK',
}


def normalise_object_type(value):
    if not value:
        return None
    value = value.strip().upper()
    return SPACETRACK_OBJECT_TYPES.get(value, value)


def normalise_stored_object_types():
    """Rewrites any full-name types already in the table (written before
    this mapping existed) as codes. Idempotent; returns rows changed."""
    changed = 0
    for longName, code in SPACETRACK_OBJECT_TYPES.items():
        changed += db.execute('UPDATE orbital_objects SET objectType = ? WHERE objectType = ?',
                              (code, longName)).rowcount
    db.commit()
    return changed


# 3. Minimal dependency-free CSV parser -- satcat.csv is a plain,
# header-led CSV with the occasional quoted field (object names can
# contain commas). Fields are looked up by header name rather than fixed
# position so a future column reorder on CelesTrak's side doesn't
# silently misalign the data.
def parse_csv_line(line):
    fields = []
    current = ''
    in_quotes = False
    i = 0
    n = len(line)
    while i < n:
        char = line[i]
        if in_quotes:
            if char == '"' and i + 1 < n and line[i + 1] == '"':
                current += '"'
                i += 1
            elif char == '"':
                in_quotes = False
            else:
                current += char
        elif char == '"':
            in_quotes = True
        elif char == ',':
            fields.append(current)
            current = ''
        else:
            current += char
        i += 1
    fields.append(current)
    return fields


def parse_satcat_csv(text):
    lines = [l.rstrip() for l in text.split('\n') if l.strip()]
    header = parse_csv_line(lines[0])

    def col(name):
        return header.index(name) if name in header else -1

    idx_norad_id = col('NORAD_CAT_ID')
    idx_object_type = col('OBJECT_TYPE')
    idx_owner = col('OWNER')
    idx_launch_date = col('LAUNCH_DATE')
    idx_launch_site = col('LAUNCH_SITE')
    idx_decay_date = col('DECAY_DATE')
    idx_rcs = col('RCS')
    idx_period = col('PERIOD')
    idx_apogee = col('APOGEE')
    idx_perigee = col('PERIGEE')

    def field_at(fields, idx):
        return fields[idx] if 0 <= idx < len(fields) else None

    def parse_float_or_none(value):
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    rows = []
    for i in range(1, len(lines)):
        fields = parse_csv_line(lines[i])
        try:
            norad_id = int(field_at(fields, idx_norad_id))
        except (TypeError, ValueError):
            continue
        rows.append({
            'noradID': norad_id,
            'objectType': normalise_object_type(field_at(fields, idx_object_type)),
            'owner': field_at(fields, idx_owner) or None,
            'launchDate': field_at(fields, idx_launch_date) or None,
            'launchSite': field_at(fields, idx_launch_site) or None,
            'decayDate': field_at(fields, idx_decay_date) or None,
            'rcsSize': parse_float_or_none(field_at(fields, idx_rcs)),
            'period': parse_float_or_none(field_at(fields, idx_period)),
            'apogee': parse_float_or_none(field_at(fields, idx_apogee)),
            'perigee': parse_float_or_none(field_at(fields, idx_perigee)),
        })
    return rows


def http_get(url, headers=None):
    """Returns (status_code, body_text) -- see ingestOrbitalData.py's
    same helper for why (normalises urllib's raise-on-4xx/5xx behaviour
    into JS fetch()'s "always get a response" shape)."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')


# 4. CelesTrak SATCAT -- primary source. A single static bulk file, not
# the per-group GP query API, so none of ingestOrbitalData.py's
# 2-hour/per-group throttling applies here.
def fetch_celestrak_satcat():
    status, text = http_get('https://celestrak.org/pub/satcat.csv')
    if status >= 400:
        raise Exception(f'HTTP {status}')
    return parse_satcat_csv(text)


# 5. Space-Track -- fallback/verification pass, only when credentials are
# configured. Reuses the same gp class already proven working in
# ingestOrbitalData.py; no EPOCH filter this time since the goal here is
# broad metadata coverage rather than "what changed recently".
SPACETRACK_USER = os.environ.get('SPACETRACK_USER')
SPACETRACK_PASS = os.environ.get('SPACETRACK_PASS')


def space_track_login():
    body = urllib.parse.urlencode({'identity': SPACETRACK_USER, 'password': SPACETRACK_PASS}).encode('utf-8')
    request = urllib.request.Request(
        'https://www.space-track.org/ajaxauth/login',
        data=body,
        method='POST',
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    try:
        with urllib.request.urlopen(request) as response:
            cookie = response.headers.get('Set-Cookie')
            body_text = response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        raise Exception(f'Space-Track login failed: HTTP {e.code}')
    if 'Failed' in body_text:
        raise Exception('Space-Track login rejected (bad credentials)')
    if not cookie:
        raise Exception('Space-Track login did not return a session cookie')
    return cookie.split(';')[0]


def fetch_space_track_satcat():
    if not SPACETRACK_USER or not SPACETRACK_PASS:
        return {'rows': [], 'skipped': True, 'note': 'no credentials configured'}
    session_cookie = space_track_login()
    query = 'https://www.space-track.org/basicspacedata/query/class/gp/format/json'
    status, text = http_get(query, headers={'Cookie': session_cookie})
    if status >= 400:
        raise Exception(f'Space-Track query failed: HTTP {status}')
    data = json.loads(text)
    rows = []
    for r in data:
        if not r.get('NORAD_CAT_ID'):
            continue
        rows.append({
            'noradID': int(r['NORAD_CAT_ID']),
            'objectType': normalise_object_type(r.get('OBJECT_TYPE')),
            'owner': r.get('COUNTRY_CODE') or None,
            'launchDate': r.get('LAUNCH_DATE') or None,
            'launchSite': r.get('SITE') or None,
            'decayDate': r.get('DECAY_DATE') or None,
            'period': float(r['PERIOD']) if r.get('PERIOD') else None,
            'apogee': float(r['APOAPSIS']) if r.get('APOAPSIS') else None,
            'perigee': float(r['PERIAPSIS']) if r.get('PERIAPSIS') else None,
        })
    return {'rows': rows, 'skipped': False}


# 5b. Etiquette controls -- same env vars and meaning as ingestOrbitalData.py
# (see its comment; set in .env, default 72 h). This script's attempts are logged in
# the shared celestrak_fetch_log table under their own key, so its interval
# runs independently of the orbital pass.
CELESTRAK_ENABLED = os.environ.get('CELESTRAK_ENABLED', '1') != '0'
CELESTRAK_INTERVAL_SEC = float(os.environ.get('CELESTRAK_INTERVAL_HOURS', '72')) * 3600
CELESTRAK_INTERVAL_SLACK_SEC = 60 * 60
SATCAT_FETCH_KEY = 'satcat.csv'

db.execute('CREATE TABLE IF NOT EXISTS celestrak_fetch_log (groupName TEXT PRIMARY KEY, lastAttempt REAL NOT NULL)')


def celestrak_satcat_due():
    """(due, reason)."""
    if not CELESTRAK_ENABLED:
        return False, 'disabled (CELESTRAK_ENABLED=0)'
    if CELESTRAK_INTERVAL_SEC <= 0:
        return True, ''
    row = db.execute('SELECT lastAttempt FROM celestrak_fetch_log WHERE groupName = ?', (SATCAT_FETCH_KEY,)).fetchone()
    if row is not None and time.time() - row[0] < CELESTRAK_INTERVAL_SEC - CELESTRAK_INTERVAL_SLACK_SEC:
        last = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(row[0]))
        return False, f'last attempt {last}, interval {CELESTRAK_INTERVAL_SEC / 3600:g}h'
    return True, ''


# 6. Main enrichment run
def run_satcat_ingestion():
    """Returns the number of objects enriched, from both sources."""
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Starting SATCAT Metadata Ingestion ===')
    seen_ids = set()
    totalEnriched = 0

    due, reason = celestrak_satcat_due()
    if not due:
        print(f'  [celestrak] skipped -- {reason}')
    else:
        try:
            db.execute('INSERT OR REPLACE INTO celestrak_fetch_log (groupName, lastAttempt) VALUES (?, ?)', (SATCAT_FETCH_KEY, time.time()))
            rows = fetch_celestrak_satcat()
            updated = 0
            for row in rows:
                cursor = db.execute(UPDATE_FROM_CELESTRAK_SQL, (
                    row['objectType'], row['owner'], row['launchDate'], row['launchSite'], row['decayDate'], row['rcsSize'],
                    row['period'], row['apogee'], row['perigee'], row['noradID'],
                ))
                if cursor.rowcount > 0:
                    updated += 1
                seen_ids.add(row['noradID'])
            print(f'  [celestrak] {len(rows)} catalogue rows read, {updated} existing objects enriched')
            totalEnriched += updated
        except Exception as err:
            print(f'  [celestrak] ERROR {err}')

    try:
        result = fetch_space_track_satcat()
        if result['skipped']:
            print(f'  [space-track] skipped ({result["note"]})')
        else:
            updated = 0
            for row in result['rows']:
                if row['noradID'] in seen_ids:
                    continue  # CelesTrak already enriched this one this run
                cursor = db.execute(UPDATE_FROM_SPACETRACK_SQL, (
                    row['objectType'], row['owner'], row['launchDate'], row['launchSite'], row['decayDate'],
                    row['period'], row['apogee'], row['perigee'], row['noradID'],
                ))
                if cursor.rowcount > 0:
                    updated += 1
            print(f'  [space-track] {updated} additional objects enriched')
            totalEnriched += updated
    except Exception as err:
        print(f'  [space-track] ERROR {err}')

    fixed = normalise_stored_object_types()
    if fixed:
        print(f'  {fixed} stored object types rewritten as codes (PAYLOAD -> PAY etc.)')
    print('=== SATCAT METADATA INGESTION COMPLETE ===\n')
    return totalEnriched


# 7. Run once and exit -- scheduling (once daily, deliberately more
# conservative than the TLE job's twice-daily cadence since object type/
# owner/launch/decay data changes on the order of days-to-never, not
# hours) is owned by cron, not this script. Each run is recorded in
# ingestionRuns for the landing page's data-freshness table.
if __name__ == '__main__':
    from ingestionLog import trackRun
    with trackRun(db, 'satcat') as run:
        run.changes = run_satcat_ingestion()
