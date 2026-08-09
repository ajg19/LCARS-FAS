"""Server side script maintaining a local cache of current orbital element
(TLE) data for on-orbit objects.

Python port of ingestOrbitalData.js -- same schema, same CelesTrak/Space-
Track/SatNOGS source priority, same source-priority-within-a-run logic via
seenIds, same rate-limit-avoidance handling for CelesTrak (response body
checked for a benign "not updated"/"no data" message before the HTTP status
is used to decide error vs. skip), same 12-hour poll interval.

The companion SATCAT enrichment job (objectType/owner/launchDate/decayDate/
rcsSize, on its own slower cadence) is a separate script, not implemented
here -- this file only ever touches the TLE-derived columns.
"""

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# Minimal stdlib .env loader (no python-dotenv dependency, matching this
# project's stdlib-only philosophy on the Python side) -- only sets
# variables not already present in the environment, same as dotenv's own
# non-overriding default behaviour.
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

# 1. Initialize local SQLite database. isolation_level=None puts the
# connection in autocommit mode, matching node:sqlite's DatabaseSync (every
# .run() call commits immediately) -- Python's sqlite3 otherwise holds an
# implicit transaction open until a explicit commit(), which would leave
# upserts undurable if this long-running process were killed mid-run.
db_path = os.path.join(BASE_DIR, 'ingestionDBs', 'orbitalObjects.db')
db = sqlite3.connect(db_path, isolation_level=None)
db.execute('PRAGMA journal_mode = WAL;')

# 2. Set up schema
db.execute('''
    CREATE TABLE IF NOT EXISTS orbital_objects (
        noradID    INTEGER PRIMARY KEY,
        name       TEXT,
        line1      TEXT,
        line2      TEXT,
        epoch      TEXT,
        objectType TEXT,
        owner      TEXT,
        launchDate TEXT,
        decayDate  TEXT,
        rcsSize    REAL,
        period     REAL,
        apogee     REAL,
        perigee    REAL,
        source     TEXT,
        fetchedAt  DATETIME DEFAULT CURRENT_TIMESTAMP
    );
''')

# period/apogee/perigee added after the table already existed in the wild --
# CREATE TABLE IF NOT EXISTS above only covers a brand-new DB. Ignoring
# "duplicate column" is the idempotent way to run this on every startup
# regardless of whether the column is already there; any other error still
# surfaces normally.
for column in ('period REAL', 'apogee REAL', 'perigee REAL'):
    try:
        db.execute(f'ALTER TABLE orbital_objects ADD COLUMN {column};')
    except sqlite3.OperationalError as err:
        if 'duplicate column name' not in str(err).lower():
            raise

# orbital_object_groups: which CelesTrak group(s) each object currently
# appears in -- a junction table (many-to-many), populated only from
# CelesTrak's per-group responses. See ingestOrbitalData.js's own comment
# for the full rationale; ported here unchanged.
db.executescript('''
    CREATE TABLE IF NOT EXISTS orbital_object_groups (
        noradID   INTEGER NOT NULL,
        groupName TEXT NOT NULL,
        PRIMARY KEY (noradID, groupName)
    );
    CREATE INDEX IF NOT EXISTS idx_orbital_object_groups_group
        ON orbital_object_groups(groupName);
''')

# 3. Upsert statements. Deliberately touches only the TLE-derived columns --
# objectType/owner/launchDate/decayDate/rcsSize belong to the separate
# SATCAT job and must survive untouched across every TLE refresh here.
UPSERT_OBJECT_SQL = '''
    INSERT INTO orbital_objects (noradID, name, line1, line2, epoch, source, fetchedAt)
    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(noradID) DO UPDATE SET
        name = excluded.name,
        line1 = excluded.line1,
        line2 = excluded.line2,
        epoch = excluded.epoch,
        source = excluded.source,
        fetchedAt = excluded.fetchedAt
'''
INSERT_GROUP_MEMBERSHIP_SQL = 'INSERT OR IGNORE INTO orbital_object_groups (noradID, groupName) VALUES (?, ?)'
DELETE_GROUP_MEMBERSHIP_SQL = 'DELETE FROM orbital_object_groups WHERE groupName = ?'

# 4. CelesTrak groups -- every group currently published under
# https://celestrak.org/NORAD/elements/. Also the values the
# /api/orbital-objects?group= endpoint filters on, so this list is the
# source of truth for both sides.
CELESTRAK_GROUPS = [
    'active', 'amateur', 'analyst', 'argos', 'beidou', 'cosmos-2251-debris',
    'cubesat', 'dmc', 'education', 'engineering', 'eutelsat',
    'fengyun-1c-debris', 'galileo', 'geo', 'geodetic', 'glo-ops',
    'globalstar', 'gnss', 'gps-ops', 'hulianwang', 'intelsat',
    'iridium-33-debris', 'iridium-NEXT', 'kuiper', 'last-30-days',
    'military', 'oneweb', 'orbcomm', 'other-comm', 'planet', 'qianfan',
    'radar', 'resource', 'sar', 'sarsat', 'satnogs', 'sbas', 'science',
    'ses', 'spire', 'starlink', 'stations', 'tdrss', 'telesat', 'visual',
    'weather', 'x-comm',
]


# 5. TLE line parsing helpers.

# Classic 5-digit catalog numbers are plain digits in columns 3-7 of line 1.
# Alpha-5 numbers (the scheme adopted once the catalog exceeds 99999)
# replace the leading digit with a letter, I and O skipped.
ALPHA5_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'


def parse_norad_id(line1):
    raw = line1[2:7]
    if raw[0].isdigit():
        return int(raw)
    letter_value = ALPHA5_LETTERS.find(raw[0].upper())
    if letter_value == -1:
        return None
    return (letter_value + 10) * 10000 + int(raw[1:])


def to_iso_string(dt):
    """Matches JS's Date.prototype.toISOString() format exactly."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


# TLE epoch field (columns 19-32 of line 1) is a 2-digit year plus
# fractional day-of-year, e.g. "24187.51782528". Years 57-99 are 1957-1999,
# 00-56 are 2000-2056 -- the standard TLE pivot year.
def parse_tle_epoch(line1):
    epoch_field = line1[18:32].strip()
    two_digit_year = int(epoch_field[0:2])
    day_of_year = float(epoch_field[2:])
    full_year = 2000 + two_digit_year if two_digit_year < 57 else 1900 + two_digit_year
    epoch_date = datetime(full_year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1)
    return to_iso_string(epoch_date)


# 6. Parse a 3LE-format response body (name line + line1 + line2, repeated)
# into {name, line1, line2} dicts.
def parse_3le(text):
    lines = [l.rstrip() for l in text.split('\n') if l.strip()]
    objects = []
    i = 0
    while i + 2 < len(lines):
        name = lines[i].strip()
        line1 = lines[i + 1]
        line2 = lines[i + 2]
        if name and line1.startswith('1 ') and line2.startswith('2 '):
            objects.append({'name': name, 'line1': line1, 'line2': line2})
        i += 3
    return objects


def http_get(url, headers=None):
    """Returns (status_code, body_text), matching JS fetch()'s "always get
    a response, check .ok yourself" behaviour -- urllib raises on 4xx/5xx by
    default, so this normalises both paths into the same return shape."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')


# 7. CelesTrak fetch -- one group at a time, throttled between requests. Per
# CelesTrak's usage policy, a repeat request inside its ~2-hour refresh
# window is answered with a "GP data has not updated..." text message
# rather than TLE data, sometimes via an actual HTTP 403 for the largest
# groups -- so the response body is checked for that message BEFORE the
# status code is used to decide error vs. skip, so a benign "already have
# the latest data" is never logged/counted as a genuine error either way.
def fetch_celestrak_group(group):
    url = f'https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=3le'
    status, text = http_get(url)
    if text.startswith('GP data has not updated') or text.startswith('No GP data found'):
        return {'objects': [], 'skipped': True, 'note': text.strip().split('\n')[0]}
    if status >= 400:
        raise Exception(f'HTTP {status}')
    return {'objects': parse_3le(text), 'skipped': False}


# 8. Space-Track -- fallback + verification pass. Only runs when
# credentials are configured via SPACETRACK_USER / SPACETRACK_PASS in .env;
# skipped otherwise so the CelesTrak-only path keeps working without an
# account.
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
    except urllib.error.HTTPError as e:
        raise Exception(f'Space-Track login failed: HTTP {e.code}')
    if not cookie:
        raise Exception('Space-Track login did not return a session cookie')
    return cookie.split(';')[0]


# Latest TLE per object, restricted to objects updated in the last 2 days --
# this pass only needs to catch recent movement CelesTrak's groups missed
# this run, not re-pull the full catalogue every time. Uses the "gp" class
# (General Perturbations) -- the legacy "tle"/"tle_latest" classes are
# retired and now 404 even unauthenticated. "gp" is already
# latest-elset-per-object, and its JSON format exposes TLE_LINE0/1/2
# directly.
def fetch_space_track():
    if not SPACETRACK_USER or not SPACETRACK_PASS:
        return {'objects': [], 'skipped': True, 'note': 'no credentials configured'}
    session_cookie = space_track_login()
    query = 'https://www.space-track.org/basicspacedata/query/class/gp/EPOCH/%3Enow-2/format/json'
    status, text = http_get(query, headers={'Cookie': session_cookie})
    if status >= 400:
        raise Exception(f'Space-Track query failed: HTTP {status}')
    rows = json.loads(text)
    objects = []
    for r in rows:
        if r.get('TLE_LINE1') and r.get('TLE_LINE2'):
            name = (r.get('OBJECT_NAME') or r.get('TLE_LINE0') or '')
            name = re.sub(r'^0 ', '', name).strip()
            objects.append({'name': name, 'line1': r['TLE_LINE1'], 'line2': r['TLE_LINE2']})
    return {'objects': objects, 'skipped': False}


# 9. SatNOGS -- supplemental pass for amateur/cubesat objects CelesTrak and
# Space-Track's mainstream catalogues don't carry. Public API, no auth.
def fetch_satnogs():
    status, text = http_get('https://db.satnogs.org/api/tle/?format=json')
    if status >= 400:
        raise Exception(f'HTTP {status}')
    rows = json.loads(text)
    return [
        {'name': r['tle0'].strip(), 'line1': r['tle1'], 'line2': r['tle2']}
        for r in rows
        if r.get('tle0') and r.get('tle1') and r.get('tle2')
    ]


# 10. Upsert a batch of parsed TLE objects tagged with which source
# supplied them. seen_ids enforces source priority within a single run --
# CelesTrak (primary) always wins; Space-Track and SatNOGS only fill in
# NORAD IDs no higher-priority source has already supplied this run.
#
# Group membership is recorded before the seen_ids check, not after --
# group is only ever passed for CelesTrak calls, and a satellite already
# seen in an earlier group this same run must still get a row for this
# group, even though seen_ids means its TLE data itself won't be
# re-upserted.
def store_objects(objects, source, seen_ids, group=None):
    count = 0
    for obj in objects:
        norad_id = parse_norad_id(obj['line1'])
        if norad_id is None:
            continue
        if group:
            db.execute(INSERT_GROUP_MEMBERSHIP_SQL, (norad_id, group))
        if norad_id in seen_ids:
            continue
        epoch = parse_tle_epoch(obj['line1'])
        db.execute(UPSERT_OBJECT_SQL, (norad_id, obj['name'], obj['line1'], obj['line2'], epoch, source))
        seen_ids.add(norad_id)
        count += 1
    return count


# 11. Main ingestion run
GROUP_DELAY_SEC = 3  # stay well clear of CelesTrak's rate limit


def run_ingestion():
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Starting Orbital Object Ingestion ===')
    seen_ids = set()

    # --- CelesTrak: primary source, one request per group ---
    celestrak_total = 0
    for group in CELESTRAK_GROUPS:
        try:
            result = fetch_celestrak_group(group)
            if result['skipped']:
                print(f'  [celestrak] {group}: skipped ({result["note"]})')
            else:
                # Replace this group's membership wholesale rather than
                # diffing -- simpler, and correct either way since we just
                # fetched every object currently in the group.
                db.execute(DELETE_GROUP_MEMBERSHIP_SQL, (group,))
                stored = store_objects(result['objects'], 'celestrak', seen_ids, group)
                celestrak_total += stored
                print(f'  [celestrak] {group}: {stored} objects')
        except Exception as err:
            print(f'  [celestrak] {group}: ERROR {err}')
        time.sleep(GROUP_DELAY_SEC)
    print(f' -> CelesTrak done. {celestrak_total} objects upserted.')

    # --- Space-Track: fallback + verification ---
    try:
        result = fetch_space_track()
        if result['skipped']:
            print(f'  [space-track] skipped ({result["note"]})')
        else:
            stored = store_objects(result['objects'], 'space-track', seen_ids)
            print(f'  [space-track] {stored} objects backfilled')
    except Exception as err:
        print(f'  [space-track] ERROR {err}')

    # --- SatNOGS: supplemental cubesat/amateur coverage ---
    try:
        objects = fetch_satnogs()
        stored = store_objects(objects, 'satnogs', seen_ids)
        print(f'  [satnogs] {stored} objects')
    except Exception as err:
        print(f'  [satnogs] ERROR {err}')

    print(f'=== ORBITAL OBJECT INGESTION COMPLETE ({len(seen_ids)} objects touched) ===\n')


# 12. Run once and exit -- scheduling (twice daily) is owned by cron, not
# this script. See readNews.py's own comment for why the self-looping
# shape was dropped in this port.
if __name__ == '__main__':
    run_ingestion()
