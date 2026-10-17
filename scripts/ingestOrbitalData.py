"""Server side script maintaining a local cache of current orbital element
(OMM) data for on-orbit objects.

Python port of ingestOrbitalData.js -- same schema shape, same CelesTrak/
Space-Track/SatNOGS source priority, same source-priority-within-a-run logic
via seenIds, same rate-limit-avoidance handling for CelesTrak (response body
checked for a benign "not updated"/"no data" message before the HTTP status
is used to decide error vs. skip), same 12-hour poll interval.

Migrated from the legacy TLE text format to CCSDS OMM (CelesTrak's
FORMAT=json), matching the frontend's move to satellite.js's json2satrec()
in place of twoline2satrec(). CelesTrak ran out of 5-digit catalog numbers
on 2026-07-11; even the Alpha-5 letter-encoding that extends classic TLE
lines has a hard ceiling (catalog #339,999), while OMM has none. The one
exception is SatNOGS, the supplemental amateur/cubesat source, which only
ever exposes raw TLE text (no JSON/OMM equivalent exists there) -- that
path alone still decodes fixed TLE columns, isolated in tle_to_omm_fields().

The companion SATCAT enrichment job (objectType/owner/launchDate/decayDate/
rcsSize, on its own slower cadence) is a separate script, not implemented
here -- this file only ever touches the orbital-element columns.
"""

import json
import os
import socket
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# The DB and .env live in the repo root; this script sits in scripts/, one level down.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

# 2. Set up schema. OMM element columns replace the old line1/line2 TLE
# text columns -- see the module docstring for why.
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

# Columns added after the table already existed in the wild -- CREATE TABLE
# IF NOT EXISTS above only covers a brand-new DB. Ignoring "duplicate
# column" is the idempotent way to run this on every startup regardless of
# whether the column is already there; any other error still surfaces
# normally. Includes the original period/apogee/perigee migration alongside
# the OMM-element columns added by the TLE->OMM migration.
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

# Drop the legacy TLE text columns now that both ingestion and the frontend
# (json2satrec, not twoline2satrec) are off them -- idempotent the same way
# as the ADD COLUMN loop above, just for the opposite direction. Requires
# SQLite >=3.35; older SQLite raises "near DROP: syntax error" instead of
# a clean "no such column", so that's caught too.
for column in ('line1', 'line2'):
    try:
        db.execute(f'ALTER TABLE orbital_objects DROP COLUMN {column};')
    except sqlite3.OperationalError as err:
        message = str(err).lower()
        if 'no such column' not in message and 'syntax error' not in message:
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
    CREATE TABLE IF NOT EXISTS celestrak_fetch_log (
        groupName   TEXT PRIMARY KEY,
        lastAttempt REAL NOT NULL
    );
''')

# 3. Upsert statement. Deliberately touches only the OMM-derived columns --
# objectType/owner/launchDate/decayDate/rcsSize belong to the separate
# SATCAT job and must survive untouched across every element refresh here.
OMM_COLUMNS = (
    'noradID', 'name', 'objectID', 'epoch', 'meanMotion', 'eccentricity',
    'inclination', 'raOfAscNode', 'argOfPericenter', 'meanAnomaly', 'bstar',
    'meanMotionDot', 'meanMotionDdot', 'source',
)
UPSERT_OBJECT_SQL = f'''
    INSERT INTO orbital_objects ({', '.join(OMM_COLUMNS)}, fetchedAt)
    VALUES ({', '.join('?' * len(OMM_COLUMNS))}, CURRENT_TIMESTAMP)
    ON CONFLICT(noradID) DO UPDATE SET
        {', '.join(f'{col} = excluded.{col}' for col in OMM_COLUMNS if col != 'noradID')},
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


# 5. OMM field mapping. CelesTrak and Space-Track both return the same
# CCSDS-defined UPPER_SNAKE keys (confirmed against both APIs' actual
# responses); this maps them onto our own camelCase DB columns.
def omm_row_from_json(entry, source):
    try:
        norad_id = int(entry['NORAD_CAT_ID'])
        epoch = entry['EPOCH']
        if not epoch.endswith('Z'):
            epoch = epoch + 'Z'
    except (KeyError, TypeError, ValueError):
        return None
    return {
        'noradID': norad_id,
        'name': (entry.get('OBJECT_NAME') or '').strip(),
        'objectID': entry.get('OBJECT_ID'),
        'epoch': epoch,
        'meanMotion': _to_float(entry.get('MEAN_MOTION')),
        'eccentricity': _to_float(entry.get('ECCENTRICITY')),
        'inclination': _to_float(entry.get('INCLINATION')),
        'raOfAscNode': _to_float(entry.get('RA_OF_ASC_NODE')),
        'argOfPericenter': _to_float(entry.get('ARG_OF_PERICENTER')),
        'meanAnomaly': _to_float(entry.get('MEAN_ANOMALY')),
        'bstar': _to_float(entry.get('BSTAR')),
        'meanMotionDot': _to_float(entry.get('MEAN_MOTION_DOT')),
        'meanMotionDdot': _to_float(entry.get('MEAN_MOTION_DDOT')),
        'source': source,
    }


def _to_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def to_iso_string(dt):
    """Matches JS's Date.prototype.toISOString() format exactly."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


# 6. SatNOGS-only TLE decoder. SatNOGS (unlike CelesTrak/Space-Track) has no
# JSON/OMM equivalent -- confirmed live against db.satnogs.org's API, which
# only ever returns tle0/tle1/tle2 text -- so this is the one place fixed
# TLE-column parsing survives, deliberately isolated to that one source.
# Column positions match the TLE spec (and satellite.js's own
# twoline2satrec parsing, so results agree with what that function would
# have produced): line1 cols 33-43 (mean motion dot, plain decimal), 44-52
# and 53-61 (mean motion ddot / bstar, assumed-decimal-point notation);
# line2 cols 8-16/17-25/26-33/34-42/43-51/52-63 (inclination/RAAN/
# eccentricity/arg of perigee/mean anomaly/mean motion).
def _decode_assumed_decimal(field):
    sign = '-' if field.startswith('-') else ''
    mantissa = field[1:-2].strip() or '0'
    exponent = field[-2:]
    return float(f'{sign}0.{mantissa}E{exponent}')


def parse_tle_epoch(line1):
    epoch_field = line1[18:32].strip()
    two_digit_year = int(epoch_field[0:2])
    day_of_year = float(epoch_field[2:])
    full_year = 2000 + two_digit_year if two_digit_year < 57 else 1900 + two_digit_year
    epoch_date = datetime(full_year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1)
    return to_iso_string(epoch_date)


def tle_to_omm_fields(norad_id, name, line1, line2, source):
    return {
        'noradID': norad_id,
        'name': name,
        'objectID': None,
        'epoch': parse_tle_epoch(line1),
        'meanMotion': float(line2[52:63]),
        'eccentricity': float(f'.{line2[26:33]}'),
        'inclination': float(line2[8:16]),
        'raOfAscNode': float(line2[17:25]),
        'argOfPericenter': float(line2[34:42]),
        'meanAnomaly': float(line2[43:51]),
        'bstar': _decode_assumed_decimal(line1[53:61]),
        'meanMotionDot': float(line1[33:43]),
        'meanMotionDdot': _decode_assumed_decimal(line1[44:52]),
        'source': source,
    }


# Every request identifies this project (CelesTrak and the other sources can
# see who is calling and how to reach us, rather than an anonymous
# "Python-urllib") and gives up after HTTP_TIMEOUT_SEC instead of hanging on
# the OS's ~2-minute connect timeout.
USER_AGENT = 'LCARS-FAS/1.0 (orbital-object ingestion; +https://github.com/ajg19/LCARS-FAS)'
HTTP_TIMEOUT_SEC = 60


def http_get(url, headers=None):
    """Returns (status_code, body_text), matching JS fetch()'s "always get
    a response, check .ok yourself" behaviour -- urllib raises on 4xx/5xx by
    default, so this normalises both paths into the same return shape.
    Connection-level failures (refused, timed out, DNS) still raise
    urllib.error.URLError."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SEC) as response:
            return response.status, response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')


# 7. CelesTrak fetch -- one group at a time, throttled between requests. Per
# CelesTrak's usage policy, a repeat request inside its ~2-hour refresh
# window is answered with a "GP data has not updated..." text message
# rather than element data (confirmed this applies to FORMAT=json exactly
# like it did to FORMAT=3le) -- sometimes via an actual HTTP 403 for the
# largest groups -- so the response body is checked for that message BEFORE
# the status code is used to decide error vs. skip, so a benign "already
# have the latest data" is never logged/counted as a genuine error either
# way.
def fetch_celestrak_group(group):
    url = f'https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=json'
    status, text = http_get(url)
    if text.startswith('GP data has not updated') or text.startswith('No GP data found'):
        return {'objects': [], 'skipped': True, 'note': text.strip().split('\n')[0]}
    if status >= 400:
        raise Exception(f'HTTP {status}')
    entries = json.loads(text)
    objects = [row for row in (omm_row_from_json(e, 'celestrak') for e in entries) if row]
    return {'objects': objects, 'skipped': False}


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


# Latest elset per object, restricted to objects updated in the last 2 days
# -- this pass only needs to catch recent movement CelesTrak's groups
# missed this run, not re-pull the full catalogue every time. Uses the "gp"
# class (General Perturbations) -- the legacy "tle"/"tle_latest" classes
# are retired and now 404 even unauthenticated. "gp" already returns the
# same CCSDS OMM field set CelesTrak's own JSON does (confirmed against
# Space-Track's own documentation), so this reuses omm_row_from_json
# unchanged rather than narrowing down to just TLE_LINE1/TLE_LINE2.
def fetch_space_track():
    if not SPACETRACK_USER or not SPACETRACK_PASS:
        return {'objects': [], 'skipped': True, 'note': 'no credentials configured'}
    session_cookie = space_track_login()
    query = 'https://www.space-track.org/basicspacedata/query/class/gp/EPOCH/%3Enow-2/format/json'
    status, text = http_get(query, headers={'Cookie': session_cookie})
    if status >= 400:
        raise Exception(f'Space-Track query failed: HTTP {status}')
    entries = json.loads(text)
    objects = [row for row in (omm_row_from_json(e, 'space-track') for e in entries) if row]
    return {'objects': objects, 'skipped': False}


# 9. SatNOGS -- supplemental pass for amateur/cubesat objects CelesTrak and
# Space-Track's mainstream catalogues don't carry. Public API, no auth.
# norad_cat_id comes through as a plain JSON int already; only the orbital
# elements themselves need decoding from the tle1/tle2 text (see
# tle_to_omm_fields()).
def fetch_satnogs():
    status, text = http_get('https://db.satnogs.org/api/tle/?format=json')
    if status >= 400:
        raise Exception(f'HTTP {status}')
    rows = json.loads(text)
    objects = []
    for r in rows:
        if not (r.get('norad_cat_id') and r.get('tle0') and r.get('tle1') and r.get('tle2')):
            continue
        name = r['tle0'].lstrip('0').strip()
        try:
            objects.append(tle_to_omm_fields(int(r['norad_cat_id']), name, r['tle1'], r['tle2'], 'satnogs'))
        except (ValueError, IndexError):
            continue
    return objects


# 10. Upsert a batch of normalised OMM-shaped objects tagged with which
# source supplied them. seen_ids enforces source priority within a single
# run -- CelesTrak (primary) always wins; Space-Track and SatNOGS only fill
# in NORAD IDs no higher-priority source has already supplied this run.
#
# Group membership is recorded before the seen_ids check, not after --
# group is only ever passed for CelesTrak calls, and a satellite already
# seen in an earlier group this same run must still get a row for this
# group, even though seen_ids means its element data itself won't be
# re-upserted.
def store_objects(objects, seen_ids, group=None):
    count = 0
    for obj in objects:
        norad_id = obj['noradID']
        if group:
            db.execute(INSERT_GROUP_MEMBERSHIP_SQL, (norad_id, group))
        if norad_id in seen_ids:
            continue
        db.execute(UPSERT_OBJECT_SQL, tuple(obj[col] for col in OMM_COLUMNS))
        seen_ids.add(norad_id)
        count += 1
    return count


# 11. Main ingestion run
GROUP_DELAY_SEC = 3  # stay well clear of CelesTrak's rate limit

# CelesTrak only refreshes GP data about every 2 hours and asks clients not
# to re-request a group inside that window, so a group attempted more
# recently than this (e.g. a manual run shortly after the cron run) is not
# asked for again. Attempts count, not just successes -- a failed request
# still cost CelesTrak a connection.
MIN_REFETCH_SEC = 2 * 60 * 60

# CelesTrak etiquette. Its firewall has dropped the live server since
# 2026-08-27 (after our 47-group sweeps); an unanswered connection is still
# a knock on their door. The code is identical everywhere; each machine's
# own .env (never deployed or committed) holds any local override:
#   CELESTRAK_ENABLED=0         no CelesTrak request at all (live server's
#                               .env, from 2026-10-17, until unblocked)
#   CELESTRAK_INTERVAL_HOURS=N  at most one CelesTrak pass per N hours,
#                               counted from the last attempt (success or
#                               not). Default 72 = once every 3 days.
# The slack lets a pass started a few minutes early by cron still count.
CELESTRAK_ENABLED = os.environ.get('CELESTRAK_ENABLED', '1') != '0'
CELESTRAK_INTERVAL_SEC = float(os.environ.get('CELESTRAK_INTERVAL_HOURS', '72')) * 3600
CELESTRAK_INTERVAL_SLACK_SEC = 60 * 60
SATCAT_FETCH_KEY = 'satcat.csv'  # ingestSatcat.py's row in celestrak_fetch_log


def celestrak_pass_due():
    """(due, reason). Gates the whole CelesTrak pass, not single groups."""
    if not CELESTRAK_ENABLED:
        return False, 'disabled (CELESTRAK_ENABLED=0)'
    if CELESTRAK_INTERVAL_SEC <= 0:
        return True, ''
    row = db.execute('SELECT MAX(lastAttempt) FROM celestrak_fetch_log WHERE groupName != ?', (SATCAT_FETCH_KEY,)).fetchone()
    if row[0] is not None and time.time() - row[0] < CELESTRAK_INTERVAL_SEC - CELESTRAK_INTERVAL_SLACK_SEC:
        last = datetime.fromtimestamp(row[0], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        return False, f'last attempt {last}, interval {CELESTRAK_INTERVAL_SEC / 3600:g}h'
    return True, ''


def celestrak_recently_attempted(group):
    row = db.execute('SELECT lastAttempt FROM celestrak_fetch_log WHERE groupName = ?', (group,)).fetchone()
    return row is not None and time.time() - row[0] < MIN_REFETCH_SEC


def record_celestrak_attempt(group):
    db.execute('INSERT OR REPLACE INTO celestrak_fetch_log (groupName, lastAttempt) VALUES (?, ?)', (group, time.time()))


def run_ingestion():
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Starting Orbital Object Ingestion ===')
    seen_ids = set()

    # --- CelesTrak: primary source, one request per group ---
    # A connection-level failure (timeout/refused) means CelesTrak is
    # unreachable or blocking this host, and every remaining group would
    # fail the same way -- so stop at the first one rather than hammering
    # all ~47 groups. HTTP errors (a response came back) don't trip this.
    celestrak_total = 0
    due, reason = celestrak_pass_due()
    if not due:
        print(f'  [celestrak] skipped -- {reason}')
    for group in (CELESTRAK_GROUPS if due else []):
        if celestrak_recently_attempted(group):
            print(f'  [celestrak] {group}: skipped (attempted < {MIN_REFETCH_SEC // 3600}h ago)')
            continue
        record_celestrak_attempt(group)
        try:
            result = fetch_celestrak_group(group)
            if result['skipped']:
                print(f'  [celestrak] {group}: skipped ({result["note"]})')
            else:
                # Replace this group's membership wholesale rather than
                # diffing -- simpler, and correct either way since we just
                # fetched every object currently in the group.
                db.execute(DELETE_GROUP_MEMBERSHIP_SQL, (group,))
                stored = store_objects(result['objects'], seen_ids, group)
                celestrak_total += stored
                print(f'  [celestrak] {group}: {stored} objects')
        except (urllib.error.URLError, socket.timeout) as err:
            print(f'  [celestrak] {group}: ERROR {err}')
            print('  [celestrak] connection failed -- skipping remaining groups this run')
            break
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
            stored = store_objects(result['objects'], seen_ids)
            print(f'  [space-track] {stored} objects backfilled')
    except Exception as err:
        print(f'  [space-track] ERROR {err}')

    # --- SatNOGS: supplemental cubesat/amateur coverage ---
    try:
        objects = fetch_satnogs()
        stored = store_objects(objects, seen_ids)
        print(f'  [satnogs] {stored} objects')
    except Exception as err:
        print(f'  [satnogs] ERROR {err}')

    print(f'=== ORBITAL OBJECT INGESTION COMPLETE ({len(seen_ids)} objects touched) ===\n')
    return len(seen_ids)


# 12. Run once and exit -- scheduling (twice daily) is owned by cron, not
# this script. See readNews.py's own comment for why the self-looping
# shape was dropped in this port. Each run is recorded in ingestionRuns for
# the landing page's data-freshness table ("changes" = objects updated).
if __name__ == '__main__':
    from ingestionLog import trackRun
    with trackRun(db, 'orbitalElements') as run:
        run.changes = run_ingestion()
