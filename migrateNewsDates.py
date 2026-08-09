"""One-time migration: normalize existing articles.published_date rows
from raw RFC 2822 text (the old, unsortable format) to ISO 8601.

Safe to run more than once -- rows that already parse as ISO 8601 are
left untouched, so re-running after readNews.py has ingested more
articles in the new format is a no-op for those rows.

Run once locally, and once again over SSH against the live database on
GoDaddy after uploading -- these are two separate databases, this script
doesn't touch both at once.
"""

import os
import sqlite3
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, 'ingestionDBs', 'space_news.db')

db = sqlite3.connect(db_path)
rows = db.execute('SELECT id, published_date FROM articles').fetchall()

migrated = 0
already_iso = 0
unparseable = 0

for article_id, raw_date in rows:
    if not raw_date:
        unparseable += 1
        continue

    # Already ISO 8601 (e.g. from a post-fix readNews.py run) -- leave alone.
    try:
        datetime.fromisoformat(raw_date)
        already_iso += 1
        continue
    except (TypeError, ValueError):
        pass

    # Old RFC 2822 format -- convert.
    try:
        parsed = parsedate_to_datetime(raw_date)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        iso_date = parsed.isoformat()
        db.execute('UPDATE articles SET published_date = ? WHERE id = ?', (iso_date, article_id))
        migrated += 1
    except (TypeError, ValueError):
        print(f'Could not parse published_date for article id={article_id}: {raw_date!r}')
        unparseable += 1

db.commit()

print(f'Migrated: {migrated}')
print(f'Already ISO 8601 (untouched): {already_iso}')
print(f'Unparseable (left as-is): {unparseable}')
