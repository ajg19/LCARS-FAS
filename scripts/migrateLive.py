"""One-off migration of a server to the refactored database layout
(step 12 of 0_documentation/dbRefactorPlan.md). Run ON the server, from
the app folder, after deploying the refactored code:

    python scripts/migrateLive.py              # dry run: checks, prints the plan, changes nothing
    python scripts/migrateLive.py --apply      # does it
    python scripts/migrateLive.py --rollback BACKUP_DIR [--apply]

WHAT --apply DOES, in order (each step printed as it runs; any failure
stops it, and the printed rollback undoes it):
  1. Checks the preconditions: old layout present (ingestionDBs/), new
     one absent (databases/), SQLite >= 3.24 (upserts), spacetrack.env
     present, every database passes a quick integrity check, enough disk
     for a full backup, no rename would overwrite anything.
  2. Saves the current crontab to the backup folder, then removes this
     app's cron jobs (lines marked LCARS-FAS-CRON) -- no old job can start
     during the migration -- and waits for any that are running to end.
  3. Backs up every database with SQLite's backup API into
     BACKUP_ROOT/dbBackup-<UTC time>/, under the old names.
  4. Checkpoints each database's WAL, renames ingestionDBs/ to
     databases/ and the files to their new names (RENAMES).
  5. Restarts the app (tmp/restart.txt): a running process still has the
     old folder name. Until the site files exist it serves the renamed
     pre-refactor databases (server.py's fallback), so the site stays up.
  6. Seeds the CelesTrak radar figures from orbitalObjects.db (decision 3
     under step 9) -- while CelesTrak blocks the server, its only source
     for EST. SIZE.
  7. First ingestion runs: Space-Track (--full), SatNOGS, CelesTrak
     (which does nothing while .env has CELESTRAK_ENABLED=0).
  8. Publishes all four site files (publishSite.py all).
  9. Installs the new crontab (setupCron.sh), which now finds databases/.
No other writer can run meanwhile: the old jobs were removed in step 2
and the new ones are installed only in step 9.

ROLLBACK (--rollback BACKUP_DIR --apply): restores the crontab saved in
BACKUP_DIR, moves databases/ aside to databases.failed-<time>/, restores
the backed-up databases into a fresh ingestionDBs/, and restarts the app.
Anything written since the backup (e.g. a bug report) stays in
databases.failed-<time>/ for copying back by hand.

Python 3.9 compatible (the live server's virtualenv). Uses only the
standard library and the project's own scripts, run as separate
processes after the rename -- dbPaths decides the folder layout at
import, so nothing that imports it is loaded here.
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS_DIR)
OLD_DIR = os.path.join(ROOT, 'ingestionDBs')
NEW_DIR = os.path.join(ROOT, 'databases')
RENAMES = {
    'gcat.db': 'ingestionGCAT.db',
    'space_news.db': 'ingestionNews.db',
    'groundSegmentAssets.db': 'ingestionGroundSegment.db',
    'skyCatalogue.db': 'ingestionSkyCatalogue.db',
    'bugReports.db': 'inboxBugReports.db',
}
CRON_MARKER = '# LCARS-FAS-CRON'
OLD_JOB_NAMES = ('runPipeline.sh', 'readNews.py', 'ingestGcat.py', 'ingestOrbitalData.py', 'ingestSatcat.py',
                 'enrichEirp.py', 'ingestSatnogsRf.py', 'orbitStats.py')
OLD_JOB_WAIT_SEC = 30 * 60
MIN_SQLITE = (3, 24, 0)


class Failed(Exception):
    pass


def say(text):
    print(text, flush=True)


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')


# --- Checks ------------------------------------------------------------------------

def databases(folder):
    return sorted(f for f in os.listdir(folder) if f.endswith('.db') and os.path.isfile(os.path.join(folder, f)))


def preconditions(backupRoot):
    """[(ok, message)] -- every check, so a dry run reports them all."""
    results = []
    results.append((os.path.isdir(OLD_DIR), f'old layout present: {OLD_DIR}'))
    results.append((not os.path.exists(NEW_DIR), f'new layout absent: {NEW_DIR}'))
    version = tuple(int(p) for p in sqlite3.sqlite_version.split('.'))
    results.append((version >= MIN_SQLITE, f'SQLite {sqlite3.sqlite_version} (need {".".join(map(str, MIN_SQLITE))}+)'))
    results.append((os.path.exists(os.path.join(ROOT, 'spacetrack.env')), 'spacetrack.env present'))
    if os.path.isdir(OLD_DIR):
        total = 0
        for name in databases(OLD_DIR):
            path = os.path.join(OLD_DIR, name)
            total += os.path.getsize(path)
            try:
                db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
                check = db.execute('PRAGMA quick_check').fetchone()[0]
                db.close()
            except sqlite3.Error as error:
                check = str(error)
            results.append((check == 'ok', f'{name}: {os.path.getsize(path) / 1e6:.1f} MB, quick_check {check}'))
            target = RENAMES.get(name)
            if target and os.path.exists(os.path.join(OLD_DIR, target)):
                results.append((False, f'rename {name} -> {target}: target already exists'))
        free = shutil.disk_usage(backupRoot).free
        results.append((free > 3 * total, f'disk: {free / 1e9:.1f} GB free, databases {total / 1e6:.0f} MB'))
    env = os.path.join(ROOT, '.env')
    if 'CELESTRAK_ENABLED' in os.environ:   # the environment wins over .env (common.loadDotenv)
        disabled, where = os.environ['CELESTRAK_ENABLED'] == '0', 'the environment'
    else:
        disabled = os.path.exists(env) and 'CELESTRAK_ENABLED=0' in open(env, encoding='utf-8').read().replace(' ', '')
        where = '.env'
    results.append((True, f'CelesTrak {"disabled (CELESTRAK_ENABLED=0)" if disabled else "ENABLED"} in {where}'))
    return results


# --- Cron and running jobs ------------------------------------------------------------

def readCrontab():
    try:
        out = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return out.stdout if out.returncode == 0 else ''


def writeCrontab(text):
    subprocess.run(['crontab', '-'], input=text, text=True, check=True)


def runningOldJobs():
    try:
        out = subprocess.run(['ps', '-eo', 'pid,args'], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return []
    me = str(os.getpid())
    return [line.strip() for line in out.splitlines()
            if any(name in line for name in OLD_JOB_NAMES) and not line.strip().startswith(me)
            and 'migrateLive' not in line]


# --- Steps ----------------------------------------------------------------------------

def backup(backupDir):
    os.makedirs(backupDir, exist_ok=True)   # the cron step may have created it
    for name in databases(OLD_DIR):
        src = sqlite3.connect(f'file:{os.path.join(OLD_DIR, name)}?mode=ro', uri=True)
        dst = sqlite3.connect(os.path.join(backupDir, name))
        src.backup(dst)
        dst.close()
        src.close()
        say(f'    backed up {name}')


def checkpointAndRename():
    for name in databases(OLD_DIR):
        db = sqlite3.connect(os.path.join(OLD_DIR, name))
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.close()
    os.rename(OLD_DIR, NEW_DIR)
    say(f'    {OLD_DIR} -> {NEW_DIR}')
    for old, new in RENAMES.items():
        for suffix in ('', '-wal', '-shm'):
            path = os.path.join(NEW_DIR, old + suffix)
            if os.path.exists(path):
                os.rename(path, os.path.join(NEW_DIR, new + suffix))
                if not suffix:
                    say(f'    {old} -> {new}')


def restartApp():
    os.makedirs(os.path.join(ROOT, 'tmp'), exist_ok=True)
    with open(os.path.join(ROOT, 'tmp', 'restart.txt'), 'a'):
        os.utime(os.path.join(ROOT, 'tmp', 'restart.txt'))
    say('    app restart requested (tmp/restart.txt)')


def runScript(*args):
    say(f'    $ {" ".join(args)}')
    code = subprocess.call([sys.executable, os.path.join(SCRIPTS_DIR, args[0]), *args[1:]], cwd=ROOT)
    if code != 0:
        raise Failed(f'{args[0]} exited {code}')


def migrate(apply, backupRoot, cron=True, restart=True):
    say(f'=== LCARS-FAS database migration ({"APPLY" if apply else "DRY RUN"}) in {ROOT}')
    checks = preconditions(backupRoot)
    for ok, message in checks:
        say(f'  [{"ok" if ok else "FAIL"}] {message}')
    if not all(ok for ok, _ in checks):
        raise Failed('preconditions not met -- nothing changed')
    backupDir = os.path.join(backupRoot, f'dbBackup-{stamp()}')
    crontab = readCrontab() if cron else None
    ours = [line for line in (crontab or '').splitlines() if CRON_MARKER in line]
    say(f'  cron: {len(ours)} LCARS-FAS jobs to remove' if cron else '  cron: skipped (--skip-cron)')
    for line in ours:
        say(f'    {line}')
    steps = ['save crontab, remove LCARS-FAS jobs, wait for running ones' if cron else None,
             f'back up {len(databases(OLD_DIR))} databases to {backupDir}',
             'checkpoint WAL, rename ingestionDBs/ -> databases/ and files: '
             + ', '.join(f'{o} -> {n}' for o, n in RENAMES.items() if os.path.exists(os.path.join(OLD_DIR, o))),
             'restart app' if restart else None,
             'seed radar figures from orbitalObjects.db',
             'ingestion: Space-Track --full, SatNOGS, CelesTrak',
             'publish all site files',
             'install new crontab (setupCron.sh)' if cron else None]
    say('  plan:')
    for i, step in enumerate(s for s in steps if s):
        say(f'    {i + 1}. {step}')
    if not apply:
        say('DRY RUN -- nothing changed. Run again with --apply to migrate.')
        return None

    say(f'  rollback if needed:  python scripts/migrateLive.py --rollback {backupDir} --apply')
    if cron:
        say('[cron] saving and removing LCARS-FAS jobs')
        os.makedirs(backupDir, exist_ok=True)
        with open(os.path.join(backupDir, 'crontab.before'), 'w', encoding='utf-8') as f:
            f.write(crontab or '')
        writeCrontab('\n'.join(line for line in (crontab or '').splitlines() if CRON_MARKER not in line) + '\n')
        deadline = time.time() + OLD_JOB_WAIT_SEC
        while runningOldJobs():
            if time.time() > deadline:
                raise Failed('old jobs still running: ' + '; '.join(runningOldJobs()))
            say('    waiting for: ' + '; '.join(runningOldJobs()))
            time.sleep(15)
    say('[backup]')
    backup(backupDir)
    say('[rename]')
    checkpointAndRename()
    if restart:
        say('[restart]')
        restartApp()
    say('[seed radar figures]')
    runScript('ingestionCelesTrak.py', '--seed-rcs', os.path.join(NEW_DIR, 'orbitalObjects.db'))
    say('[ingestion]')
    runScript('ingestionSpaceTrack.py', '--full')
    runScript('ingestionSatNOGS.py')
    runScript('ingestionCelesTrak.py')
    say('[publish]')
    runScript('publishSite.py', 'all')
    if cron:
        say('[cron] installing the new crontab')
        subprocess.run(['bash', os.path.join(ROOT, 'setupCron.sh')], cwd=ROOT, check=True)
    say(f'=== MIGRATION COMPLETE. Backup: {backupDir}')
    return backupDir


def rollback(backupDir, apply, cron=True, restart=True):
    say(f'=== LCARS-FAS rollback ({"APPLY" if apply else "DRY RUN"}) from {backupDir}')
    saved = databases(backupDir)
    aside = f'{NEW_DIR}.failed-{stamp()}'
    hasCron = os.path.exists(os.path.join(backupDir, 'crontab.before'))
    say(f'  backup holds {len(saved)} databases: {", ".join(saved)}')
    say(f'  plan: {"restore crontab; " if cron and hasCron else ""}move {NEW_DIR} -> {aside}; '
        f'restore databases into {OLD_DIR}{"; restart app" if restart else ""}')
    if not saved:
        raise Failed('no databases in the backup folder')
    if os.path.exists(OLD_DIR):
        raise Failed(f'{OLD_DIR} already exists -- nothing changed')
    if not apply:
        say('DRY RUN -- nothing changed. Run again with --apply to roll back.')
        return
    if cron and hasCron:
        writeCrontab(open(os.path.join(backupDir, 'crontab.before'), encoding='utf-8').read())
        say('    crontab restored')
    if os.path.exists(NEW_DIR):
        os.rename(NEW_DIR, aside)
        say(f'    {NEW_DIR} -> {aside}')
    os.makedirs(OLD_DIR)
    for name in saved:
        shutil.copy2(os.path.join(backupDir, name), os.path.join(OLD_DIR, name))
    say(f'    {len(saved)} databases restored into {OLD_DIR}')
    if restart:
        restartApp()
    say('=== ROLLBACK COMPLETE')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Migrate this server to the refactored database layout.')
    parser.add_argument('--apply', action='store_true', help='make the changes (default: dry run)')
    parser.add_argument('--rollback', metavar='BACKUP_DIR', help='undo a migration from its backup folder')
    parser.add_argument('--backup-root', default=os.path.expanduser('~'), help='where dbBackup-<time>/ goes')
    parser.add_argument('--skip-cron', action='store_true', help='leave the crontab alone (DEV rehearsal)')
    parser.add_argument('--skip-restart', action='store_true', help="don't touch tmp/restart.txt (DEV rehearsal)")
    args = parser.parse_args(argv)
    try:
        if args.rollback:
            rollback(args.rollback, args.apply, not args.skip_cron, not args.skip_restart)
        else:
            migrate(args.apply, args.backup_root, not args.skip_cron, not args.skip_restart)
    except Failed as error:
        say(f'STOPPED: {error}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
