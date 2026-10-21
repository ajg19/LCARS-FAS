"""CelesTrak ingestion: keeps databases/ingestionCelesTrak.db holding the
membership of CelesTrak's satellite groups (active, stations, starlink,
gps-ops, ...) -- which objects are in which group, nothing else.

Step 6 of 0_documentation/dbRefactorPlan.md. Since the refactor CelesTrak
supplies no orbital elements (Space-Track does, see
ingestionSpaceTrack.py); it is kept for its group lists only. Under
decision A, the publish step treats a group list as definitive for the
objects it covers whenever CelesTrak is "available" -- fetched recently
enough -- and falls back to our own rules otherwise. groupFetches records
when each group was last fetched successfully, so the publish step can
tell.

Etiquette. CelesTrak's firewall has dropped the live server since
2026-08-27, after our old twice-daily sweeps of every group. This script
asks for each group at most once a week:
  CELESTRAK_ENABLED=0                 no CelesTrak request at all (the
                                      live server's .env, until unblocked)
  CELESTRAK_GROUPS_INTERVAL_HOURS=N   at most one pass per N hours,
                                      counted from the last attempt,
                                      successful or not. Default 168.
Groups are requested one at a time, GROUP_DELAY_SEC apart, and a pass
stops at the first connection failure (refused or timed out means
blocked or down -- the remaining groups would fail the same way).
Elements come back with the membership whatever the format; CSV is the
smallest, and only the NORAD ID and name are kept.

RADAR CROSS-SECTION (decided 2026-10-21). CelesTrak's catalogue file
(satcat.csv) is the only source of a numeric radar cross-section in m^2
-- Space-Track gives just SMALL / MEDIUM / LARGE -- and the website shows
it as EST. SIZE. Satellites don't change size, so a figure once known is
kept for good: table satcatRcs is only ever added to or updated, never
emptied, and a blank from CelesTrak never replaces a figure we hold. Each
full weekly pass ends with one satcat.csv request; --seed-rcs imports
the figures the old orbitalObjects.db already holds (a one-off, on DEV
and in the live server's migration), without overwriting any.

Every run is recorded in ingestionRuns (job celesTrakGroups); "changes"
counts memberships added or removed and radar figures added or changed,
which is what triggers a publish (decision C1).
"""

import argparse
import calendar
import csv
import io
import os
import socket
import sqlite3
import sys
import time
import urllib.error

from common import httpGet, loadProjectEnv
from dbPaths import CELESTRAK_DB, dbPath
from ingestionLog import trackRun, utcNowIso

# Every group CelesTrak publishes under https://celestrak.org/NORAD/elements/.
# The website's ADD OBJ search offers whichever of these have members.
GROUPS = [
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
GROUP_URL = 'https://celestrak.org/NORAD/elements/gp.php?GROUP={}&FORMAT=csv'
SATCAT_URL = 'https://celestrak.org/pub/satcat.csv'
GROUP_DELAY_SEC = 3
DEFAULT_INTERVAL_HOURS = 168
# A cron run started a little early still counts as a week.
INTERVAL_SLACK_SEC = 60 * 60
JOB = 'celesTrakGroups'


def openDb(path=None):
    db = sqlite3.connect(path or dbPath(CELESTRAK_DB))
    db.execute('PRAGMA journal_mode = WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS groupMembers (
            groupName  TEXT NOT NULL,
            noradID    INTEGER NOT NULL,
            objectName TEXT,
            PRIMARY KEY (groupName, noradID)
        );
        CREATE INDEX IF NOT EXISTS groupMembersByNorad ON groupMembers (noradID);
        CREATE TABLE IF NOT EXISTS groupFetches (
            groupName   TEXT PRIMARY KEY,
            lastAttempt TEXT NOT NULL,
            lastSuccess TEXT,
            members     INTEGER,
            note        TEXT
        );
        CREATE TABLE IF NOT EXISTS satcatRcs (
            noradID   INTEGER PRIMARY KEY,
            rcsM2     REAL NOT NULL,
            source    TEXT NOT NULL,
            firstSeen TEXT NOT NULL,
            lastSeen  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS satcatFetches (
            fileName    TEXT PRIMARY KEY,
            lastAttempt TEXT NOT NULL,
            lastSuccess TEXT,
            rcsValues   INTEGER,
            note        TEXT
        );
    ''')
    db.commit()
    return db


def settings():
    loadProjectEnv()
    enabled = os.environ.get('CELESTRAK_ENABLED', '1') != '0'
    hours = float(os.environ.get('CELESTRAK_GROUPS_INTERVAL_HOURS', DEFAULT_INTERVAL_HOURS))
    return enabled, hours * 3600


def passDue(db, intervalSec, now=None):
    """(due, reason). Counts attempts, not just successes: a failed
    request still knocked on CelesTrak's door."""
    if intervalSec <= 0:
        return True, ''
    last = db.execute('SELECT MAX(lastAttempt) FROM groupFetches').fetchone()[0]
    if last is None:
        return True, ''
    age = (now or time.time()) - calendar.timegm(time.strptime(last, '%Y-%m-%dT%H:%M:%SZ'))
    if age < intervalSec - INTERVAL_SLACK_SEC:
        return False, f'last attempt {last}, interval {intervalSec / 3600:g}h'
    return True, ''


def parseMembers(text):
    """[(noradID, objectName)] from a gp.php CSV response."""
    members = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            members.append((int(row['NORAD_CAT_ID']), (row.get('OBJECT_NAME') or '').strip()))
        except (KeyError, TypeError, ValueError):
            continue
    return members


def fetchGroup(group):
    """('ok', members) | ('skipped', note). Raises on HTTP errors;
    connection failures raise URLError / socket.timeout."""
    status, text = httpGet(GROUP_URL.format(group))
    # CelesTrak answers a repeat request inside its ~2-hour refresh window
    # with a message instead of data -- sometimes with HTTP 403 -- so the
    # body is checked before the status.
    if text.startswith('GP data has not updated') or text.startswith('No GP data found'):
        return 'skipped', text.strip().split('\n')[0]
    if status >= 400:
        raise Exception(f'HTTP {status}')
    members = parseMembers(text)
    if not members:
        raise Exception('no members in response')
    return 'ok', members


def storeGroup(db, group, members, now):
    """Replaces the group's membership in one transaction. Returns the
    number of memberships added plus removed."""
    new = {norad for norad, _ in members}
    with db:
        old = {r[0] for r in db.execute('SELECT noradID FROM groupMembers WHERE groupName = ?', (group,))}
        db.execute('DELETE FROM groupMembers WHERE groupName = ?', (group,))
        db.executemany('INSERT OR IGNORE INTO groupMembers (groupName, noradID, objectName) VALUES (?, ?, ?)',
                       [(group, norad, name) for norad, name in members])
        db.execute('UPDATE groupFetches SET lastSuccess = ?, members = ?, note = NULL WHERE groupName = ?',
                   (now, len(new), group))
    return len(new ^ old)


def recordAttempt(db, group, now, note=None):
    with db:
        db.execute('INSERT INTO groupFetches (groupName, lastAttempt, note) VALUES (?, ?, ?) '
                   'ON CONFLICT(groupName) DO UPDATE SET lastAttempt = excluded.lastAttempt, note = excluded.note',
                   (group, now, note))


def runPass(db, groups, fetch=fetchGroup, delay=GROUP_DELAY_SEC):
    """Returns (changes, succeeded, failed, note)."""
    changes, succeeded, failed, notes = 0, 0, 0, []
    for i, group in enumerate(groups):
        now = utcNowIso()
        recordAttempt(db, group, now)
        try:
            outcome, result = fetch(group)
            if outcome == 'skipped':
                recordAttempt(db, group, now, result)
                print(f'  {group}: skipped ({result})')
            else:
                changed = storeGroup(db, group, result, now)
                changes += changed
                succeeded += 1
                print(f'  {group}: {len(result)} members, {changed} changed')
        except (urllib.error.URLError, socket.timeout) as error:
            failed += 1
            recordAttempt(db, group, now, f'connection failed: {error}'[:300])
            notes.append(f'connection failed at {group}; remaining groups skipped')
            print(f'  {group}: connection failed ({error}) -- skipping the remaining groups')
            break
        except Exception as error:
            failed += 1
            recordAttempt(db, group, now, f'{type(error).__name__}: {error}'[:300])
            notes.append(f'{group}: {error}')
            print(f'  {group}: ERROR {error}')
        if i < len(groups) - 1:
            time.sleep(delay)
    note = f'{succeeded} groups fetched, {failed} failed' + (f'; {"; ".join(notes)}' if notes else '')
    return changes, succeeded, failed, note[:500]


# --- Radar cross-section (satcat.csv) ------------------------------------------

def parseSatcatRcs(text):
    """[(noradID, rcsM2)] for every catalogue row with a positive RCS."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            norad, rcs = int(row['NORAD_CAT_ID']), float(row['RCS'])
        except (KeyError, TypeError, ValueError):
            continue
        if rcs > 0:
            rows.append((norad, rcs))
    return rows


def fetchSatcat():
    status, text = httpGet(SATCAT_URL)
    if status >= 400:
        raise Exception(f'HTTP {status}')
    rows = parseSatcatRcs(text)
    if not rows:
        raise Exception('no RCS values in satcat.csv')
    return rows


def storeRcs(db, rows, now, source='celestrak satcat', overwrite=True):
    """Adds or updates radar figures; never removes one. overwrite=False
    (the seed) only fills objects with no figure yet. Returns the number
    of figures added or changed."""
    with db:
        held = dict(db.execute('SELECT noradID, rcsM2 FROM satcatRcs'))
        changed = sum(1 for norad, rcs in rows if norad not in held or (overwrite and held[norad] != rcs))
        db.executemany(
            'INSERT INTO satcatRcs (noradID, rcsM2, source, firstSeen, lastSeen) VALUES (?, ?, ?, ?, ?) '
            'ON CONFLICT(noradID) DO UPDATE SET rcsM2 = excluded.rcsM2, source = excluded.source, '
            'lastSeen = excluded.lastSeen' + ('' if overwrite else ' WHERE 0'),
            [(norad, rcs, source, now, now) for norad, rcs in rows])
    return changed


def recordSatcatFetch(db, now, values=None, note=None):
    with db:
        db.execute('INSERT INTO satcatFetches (fileName, lastAttempt) VALUES (?, ?) '
                   'ON CONFLICT(fileName) DO UPDATE SET lastAttempt = excluded.lastAttempt', ('satcat.csv', now))
        if values is not None:
            db.execute("UPDATE satcatFetches SET lastSuccess = ?, rcsValues = ?, note = NULL WHERE fileName = 'satcat.csv'",
                       (now, values))
        elif note:
            db.execute("UPDATE satcatFetches SET note = ? WHERE fileName = 'satcat.csv'", (note[:300],))


def runSatcat(db, fetch=fetchSatcat):
    """One satcat.csv request. Returns (changes, ok, note)."""
    now = utcNowIso()
    recordSatcatFetch(db, now)
    try:
        rows = fetch()
    except Exception as error:
        recordSatcatFetch(db, now, note=f'{type(error).__name__}: {error}')
        print(f'  satcat.csv: ERROR {error}')
        return 0, False, f'satcat.csv: {error}'
    changed = storeRcs(db, rows, now)
    recordSatcatFetch(db, now, values=len(rows))
    print(f'  satcat.csv: {len(rows)} radar figures, {changed} added or changed')
    return changed, True, f'satcat.csv {len(rows)} RCS, {changed} changed'


def seedRcs(db, orbitalPath):
    """One-off: the CelesTrak radar figures the old orbitalObjects.db holds
    (its rcsSize was only ever set from CelesTrak's satcat), added where
    we have none. Returns the number added."""
    old = sqlite3.connect(f'file:{orbitalPath}?mode=ro', uri=True)
    rows = old.execute('SELECT noradID, rcsSize FROM orbital_objects WHERE rcsSize > 0').fetchall()
    old.close()
    added = storeRcs(db, rows, utcNowIso(), 'celestrak satcat (seeded from orbitalObjects.db)', overwrite=False)
    print(f'  seed: {len(rows)} radar figures in {orbitalPath}, {added} added')
    return added


def main(argv=None):
    parser = argparse.ArgumentParser(description='CelesTrak group membership into ingestionCelesTrak.db.')
    parser.add_argument('--force', action='store_true', help='ignore the weekly interval (not CELESTRAK_ENABLED)')
    parser.add_argument('--groups', help='comma-separated subset of groups (default: all; no satcat.csv)')
    parser.add_argument('--seed-rcs', metavar='ORBITAL_DB',
                        help='one-off: import radar figures from the old orbitalObjects.db, then stop')
    args = parser.parse_args(argv)

    if args.seed_rcs:
        db = openDb()
        seedRcs(db, args.seed_rcs)
        db.close()
        return 0

    groups = args.groups.split(',') if args.groups else GROUPS
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        parser.error(f'unknown group(s): {", ".join(unknown)}')

    enabled, intervalSec = settings()
    db = openDb()
    print(f'\n=== [{time.strftime("%H:%M:%S")}] CelesTrak groups ===')
    if not enabled:
        print('  skipped -- disabled (CELESTRAK_ENABLED=0)')
        return 0
    due, reason = passDue(db, intervalSec)
    if not due and not args.force:
        print(f'  skipped -- {reason}')
        return 0
    with trackRun(db, JOB) as run:
        run.changes, succeeded, failed, run.note = runPass(db, groups)
        # A full pass ends with the catalogue file, unless CelesTrak has
        # stopped answering (the group loop then broke off at a
        # connection failure and fetched nothing).
        if not args.groups and succeeded:
            time.sleep(GROUP_DELAY_SEC)
            changed, ok, note = runSatcat(db)
            run.changes += changed
            run.note = f'{run.note}; {note}'[:500]
        # A pass where nothing arrived is a failure; some groups failing
        # is noted but still a successful pass.
        run.failed = succeeded == 0 and failed > 0
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} changes')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
