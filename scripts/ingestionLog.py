"""Records each run of an ingestion job -- when it ran, whether it
succeeded, and how many records it changed -- for the landing page's
data-freshness table (api/status in server.py).

Each job logs into its OWN database's ingestionRuns table (news into
space_news.db, the orbital pipeline into orbitalObjects.db), keeping to
the one-database-per-domain rule rather than sharing a log file.

Usage, from a job's __main__ block:

    with trackRun(db, 'news') as run:
        run.changes = fetch_all_feeds()

An exception inside the block is recorded as a failed run, then re-raised
so the job still fails loudly in its cron log. Setting run.failed = True
records a failure without raising (for a job that catches its own error).
"""

from contextlib import contextmanager
from datetime import datetime, timezone

# Rows kept per job -- enough history to see a pattern of failures, small
# enough that the table never needs thinking about.
KEEP_RUNS_PER_JOB = 100


def utcNowIso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def ensureRunsTable(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS ingestionRuns (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            job        TEXT NOT NULL,
            startedAt  TEXT NOT NULL,
            finishedAt TEXT NOT NULL,
            succeeded  INTEGER NOT NULL,
            changes    INTEGER,
            note       TEXT
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS ingestionRunsByJob ON ingestionRuns (job, finishedAt)')
    db.commit()


def recordRun(db, job, startedAt, succeeded, changes=None, note=None):
    ensureRunsTable(db)
    db.execute(
        'INSERT INTO ingestionRuns (job, startedAt, finishedAt, succeeded, changes, note) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (job, startedAt, utcNowIso(), 1 if succeeded else 0, changes, note),
    )
    db.execute('''
        DELETE FROM ingestionRuns WHERE job = ? AND id NOT IN (
            SELECT id FROM ingestionRuns WHERE job = ? ORDER BY id DESC LIMIT ?
        )
    ''', (job, job, KEEP_RUNS_PER_JOB))
    db.commit()


class _Run:
    def __init__(self):
        self.changes = None
        self.failed = False
        self.note = None


@contextmanager
def trackRun(db, job):
    run = _Run()
    startedAt = utcNowIso()
    try:
        yield run
    except BaseException as error:
        recordRun(db, job, startedAt, False, run.changes, f'{type(error).__name__}: {error}'[:500])
        raise
    recordRun(db, job, startedAt, not run.failed, run.changes, run.note)
