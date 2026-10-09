"""Keeps the news database to real news from the last six months.

Deletes, in order:
  1. filler -- anything fillerRules.classifyFiller() flags. readNews.py
     never stores filler, so this only finds rows stored before a rule
     existed; it's what makes a rule change apply to past articles too.
  2. duplicates -- a later row with the same source and title as an
     earlier one (e.g. NASA republishing an APOD under a second URL).
  3. anything older than RETENTION_MONTHS.
then VACUUMs, since SQLite only reuses the space deleted rows leave behind
-- the file itself never shrinks without one.

readNews.py calls pruneNews() and vacuumDatabase() at the end of every
run. Run by hand with --dry-run to see what would go without deleting
anything, and --months to test the age cutoff against data that's all
recent:

    python scripts/pruneNews.py --dry-run
    python scripts/pruneNews.py --dry-run --months 1
    python scripts/pruneNews.py

Deletions are permanent -- back up ingestionDBs/space_news.db first.
"""

import argparse
import os
import sqlite3
import sys

from fillerRules import classifyFiller
from tagNews import ensureTopicsTable, storeTopicCounts

RETENTION_MONTHS = 6

# The DB lives in the repo root's ingestionDBs/; this script sits in scripts/, one level down.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'ingestionDBs', 'space_news.db')


def findFiller(db):
    rows = db.execute('SELECT id, source, title FROM articles').fetchall()
    found = []
    for articleID, source, title in rows:
        ruleName = classifyFiller(source, title)
        if ruleName:
            found.append((articleID, ruleName, title))
    return found


def findDuplicates(db):
    rows = db.execute('''
        SELECT a.id, a.title FROM articles a
        WHERE EXISTS (
            SELECT 1 FROM articles b
            WHERE b.source = a.source AND b.title = a.title AND b.id < a.id
        )
    ''').fetchall()
    return [(articleID, 'duplicate', title) for articleID, title in rows]


def findExpired(db, months):
    # published_date is ISO 8601 for every parseable feed date, but
    # 'Unknown Date' where the feed's date couldn't be parsed -- and as text
    # that sorts after every real date, so it would never expire. Those
    # rows fall back to fetched_at instead.
    rows = db.execute('''
        SELECT id, title FROM articles
        WHERE (CASE WHEN published_date GLOB '[0-9][0-9][0-9][0-9]-*'
                    THEN published_date ELSE fetched_at END) < date('now', ?)
    ''', (f'-{months} months',)).fetchall()
    return [(articleID, f'older than {months} months', title) for articleID, title in rows]


def pruneNews(db, months=RETENTION_MONTHS, dryRun=False, verbose=False):
    """Deletes filler, duplicates and expired articles (or, with dryRun,
    only reports them). Returns {reason: count}."""
    toDelete = {}
    for finder in (findFiller, findDuplicates, lambda conn: findExpired(conn, months)):
        for articleID, reason, title in finder(db):
            toDelete.setdefault(articleID, (reason, title))

    counts = {}
    for reason, title in toDelete.values():
        counts[reason] = counts.get(reason, 0) + 1

    if verbose:
        for reason in sorted(counts):
            print(f'== {reason} ({counts[reason]})')
            for articleReason, title in toDelete.values():
                if articleReason == reason:
                    print(f'   {(title or "").strip()}')

    if not dryRun and toDelete:
        db.executemany('DELETE FROM articles WHERE id = ?', [(articleID,) for articleID in toDelete])
        # Topics of deleted articles -- tagNews.py rebuilds this table on
        # every readNews.py run anyway, but a standalone prune shouldn't
        # leave orphans behind in the meantime.
        hasTopicsTable = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'articleTopics'"
        ).fetchone()
        if hasTopicsTable:
            db.execute('DELETE FROM articleTopics WHERE articleID NOT IN (SELECT id FROM articles)')
            # Keep the histogram's stored counts in step with the deletes.
            ensureTopicsTable(db)
            storeTopicCounts(db)
        db.commit()

    return counts


def vacuumDatabase(db):
    """VACUUM can't run inside a transaction, and fails if server.py is
    mid-read at that instant -- in which case it's simply skipped until the
    next run, 30 minutes later, rather than failing the ingest."""
    db.commit()
    try:
        db.execute('VACUUM')
        return True
    except sqlite3.OperationalError as error:
        print(f' -> VACUUM skipped: {error}')
        return False


if __name__ == '__main__':
    # Titles contain characters the Windows console's code page can't
    # print; replace them rather than crash mid-report.
    sys.stdout.reconfigure(errors='replace')

    parser = argparse.ArgumentParser(description='Delete filler, duplicate and old news articles, then VACUUM.')
    parser.add_argument('--dry-run', action='store_true', help='list what would be deleted; change nothing')
    parser.add_argument('--months', type=int, default=RETENTION_MONTHS, help='age cutoff (default: %(default)s)')
    args = parser.parse_args()

    db = sqlite3.connect(DB_PATH)
    articlesBefore = db.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
    bytesBefore = os.path.getsize(DB_PATH)

    counts = pruneNews(db, months=args.months, dryRun=args.dry_run, verbose=True)
    total = sum(counts.values())

    if args.dry_run:
        print(f'\nDRY RUN -- would delete {total} of {articlesBefore} articles. Nothing changed.')
    else:
        vacuumDatabase(db)
        articlesAfter = db.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
        db.close()
        print(f'\nDeleted {total}: {articlesBefore} -> {articlesAfter} articles, '
              f'{bytesBefore // 1024} KB -> {os.path.getsize(DB_PATH) // 1024} KB')
