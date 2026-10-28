"""Runs one source's ingestion, then publishes the site files built from
that source if the run changed anything. What cron calls (setupCron.sh).

Step 11 of 0_documentation/plans/dbRefactorPlan.md, decision C:
  C1  each ingestion that changed something publishes the site files
      that depend on it -- and only then;
  C2  a failed or skipped run publishes nothing, so the site keeps the
      last good data; a stale source shows in the freshness table.

    python scripts/runIngestion.py spaceTrack|satnogs|celesTrak|gcat|news|swpcFast|swpcSlow|swpcMaps|swpcPrune|gfz|donki|gcr|gcrMonthly|silso|tecCode|tecGlotec

ONE RUN:
  1. Take the shared lock (LOCK_NAME in the database folder), waiting up
     to LOCK_WAIT_SEC -- every writer of databases/ goes through here, so
     an ingestion never overlaps a publish. (Locking needs fcntl, i.e.
     Linux; on the Windows DEV box runs are by hand and the lock is
     skipped.)
  2. Run the source's ingestion script as its own process.
  3. Read the run it recorded in its database's ingestionRuns.
  4. If that run succeeded with changes > 0, publish each dependent
     site file (publishSite.publish). A refused publish leaves the live
     file as it was and makes this run exit non-zero.
The exit code is the ingestion's, or 1 if a publish was refused.
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from dbPaths import (CELESTRAK_DB, DB_DIR, DONKI_DB, GCAT_DB, GCR_DB, GFZ_DB, NEWS_DB, SATNOGS_DB, SILSO_DB,
                     SPACETRACK_DB, SWPC_DB, TEC_DB, dbPath)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_NAME = '.writers.lock'
LOCK_WAIT_SEC = 15 * 60

# source -> (ingestion script, its database, the jobs it records, site files it feeds)
SOURCES = {
    'spaceTrack': ('ingestionSpaceTrack.py', SPACETRACK_DB, ('spaceTrackFull', 'spaceTrackRecent'), ('orbital',)),
    'satnogs':    ('ingestionSatNOGS.py', SATNOGS_DB, ('satnogs',), ('orbital',)),
    'celesTrak':  ('ingestionCelesTrak.py', CELESTRAK_DB, ('celesTrakGroups',), ('orbital',)),
    'gcat':       ('ingestGcat.py', GCAT_DB, ('gcat',), ('orbital',)),
    'news':       ('readNews.py', NEWS_DB, ('news',), ('news',)),
    # Space weather: every changing run republishes siteWeather.db. swpcPrune
    # only deletes old rows from the ingestion database, so it publishes nothing.
    'swpcFast':   ('ingestionSWPC.py', SWPC_DB, ('swpcFast',), ('weather',)),
    'swpcSlow':   ('ingestionSWPC.py', SWPC_DB, ('swpcSlow',), ('weather',)),
    'swpcMaps':   ('ingestionSWPC.py', SWPC_DB, ('swpcMaps',), ('weather',)),
    'swpcPrune':  ('ingestionSWPC.py', SWPC_DB, ('swpcPrune',), ()),   # daily: deletes 1-minute rows past 90 days
    'gfz':        ('ingestionGFZ.py', GFZ_DB, ('gfz',), ('weather',)),
    'donki':      ('ingestionDONKI.py', DONKI_DB, ('donki',), ('weather',)),
    'gcr':        ('ingestionGCR.py', GCR_DB, ('gcr',), ('weather',)),
    'gcrMonthly': ('ingestionGCR.py', GCR_DB, ('gcrMonthly',), ('weather',)),
    'silso':      ('ingestionSILSO.py', SILSO_DB, ('silso',), ('weather',)),
    'tecCode':    ('ingestionTEC.py', TEC_DB, ('tecCode',), ('weather',)),     # daily: CODE (Bern) observed and predicted TEC maps
    'tecGlotec':  ('ingestionTEC.py', TEC_DB, ('tecGlotec',), ('weather',)),   # 3-hourly: NOAA GloTEC, newest map
}

# Sources whose script takes arguments (one script, several jobs).
SCRIPT_ARGS = {
    'swpcFast': ('--job', 'swpcFast'),
    'swpcSlow': ('--job', 'swpcSlow'),
    'swpcMaps': ('--job', 'swpcMaps'),
    'swpcPrune': ('--job', 'swpcPrune'),
    'gcrMonthly': ('--monthly',),
    'tecCode': ('--job', 'tecCode'),
    'tecGlotec': ('--job', 'tecGlotec'),
}


class Lock:
    """Exclusive lock on a file in the database folder, waiting up to
    `wait` seconds. A no-op where fcntl doesn't exist (Windows)."""

    def __init__(self, path, wait=LOCK_WAIT_SEC):
        self.path, self.wait, self.handle = path, wait, None

    def __enter__(self):
        try:
            import fcntl
        except ImportError:
            return self
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, 'a')
        deadline = time.time() + self.wait
        while True:
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() > deadline:
                    self.handle.close()
                    raise TimeoutError(f'{self.path} still locked after {self.wait} s')
                time.sleep(5)

    def __exit__(self, *exc):
        if self.handle:
            self.handle.close()   # closing releases the flock
        return False


def recordedRun(dbFile, jobs, since):
    """(succeeded, changes) of the newest run of `jobs` that finished at or
    after `since`, or None when the script recorded none (e.g. CelesTrak
    skipped because its interval hasn't passed)."""
    import sqlite3
    path = dbPath(dbFile)
    if not os.path.exists(path):
        return None
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        row = db.execute(f'SELECT succeeded, changes FROM ingestionRuns WHERE job IN ({",".join("?" * len(jobs))}) '
                         'AND finishedAt >= ? ORDER BY finishedAt DESC LIMIT 1', (*jobs, since)).fetchone()
    except sqlite3.OperationalError:
        row = None   # no ingestionRuns table yet
    finally:
        db.close()
    return row


def runSource(source, run=subprocess.call, publish=None):
    """Returns the exit code. run/publish are injectable for tests."""
    if publish is None:
        from publishSite import publish
    script, dbFile, jobs, kinds = SOURCES[source]
    started = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f'\n##### [{time.strftime("%Y-%m-%d %H:%M:%S")}] {source}: {script}', flush=True)
    code = run([sys.executable, os.path.join(SCRIPTS_DIR, script), *SCRIPT_ARGS.get(source, ())])
    recorded = recordedRun(dbFile, jobs, started)
    if recorded is None:
        print(f'  {source}: no run recorded -- nothing to publish')
        return code
    succeeded, changes = recorded
    if not succeeded or not changes:
        print(f'  {source}: {"failed" if not succeeded else "no changes"} -- nothing to publish')
        return code
    for kind in kinds:
        try:
            counts = publish(kind)
            print(f'  published {kind}: ' + ', '.join(f'{t} {n}' for t, n in counts.items()))
        except Exception as error:
            print(f'  publish {kind} REFUSED -- {type(error).__name__}: {error}')
            code = code or 1
    return code


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in SOURCES:
        print(f'usage: runIngestion.py {"|".join(SOURCES)}', file=sys.stderr)
        return 2
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    with Lock(os.path.join(DB_DIR, LOCK_NAME)):
        return runSource(argv[0])


if __name__ == '__main__':
    sys.exit(main())
