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

Every run is recorded in ingestionRuns (job celesTrakGroups); "changes"
counts memberships added or removed, which is what triggers a publish
(decision C1).
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


def main(argv=None):
    parser = argparse.ArgumentParser(description='CelesTrak group membership into ingestionCelesTrak.db.')
    parser.add_argument('--force', action='store_true', help='ignore the weekly interval (not CELESTRAK_ENABLED)')
    parser.add_argument('--groups', help='comma-separated subset of groups (default: all)')
    args = parser.parse_args(argv)

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
        # A pass where nothing arrived is a failure; some groups failing
        # is noted but still a successful pass.
        run.failed = succeeded == 0 and failed > 0
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} memberships changed')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
