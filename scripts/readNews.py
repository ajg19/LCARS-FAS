"""Server side script maintaining a lightweight database of space news.

Python port of readNews.js -- same schema, same feed list, same regex-based
RSS parsing (no XML library dependency, matching the original's own
"no external dependencies" choice), same 7-day/100-item selection logic,
same 1-second delay between feeds, same 30-minute poll loop.
"""

import os
import re
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from fillerRules import classifyFiller
from ingestionLog import trackRun
from pruneNews import pruneNews, vacuumDatabase
from tagNews import retagAllArticles

# The DB and .env live in the repo root; this script sits in scripts/, one level down.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1. Initialize local SQLite database
db_path = os.path.join(BASE_DIR, 'ingestionDBs', 'space_news.db')
db = sqlite3.connect(db_path)

# 2. Set up schema
db.execute('''
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        title TEXT,
        url TEXT UNIQUE,
        published_date TEXT,
        fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
''')

# Migration for databases created before the description column existed --
# CREATE TABLE IF NOT EXISTS above doesn't touch an already-existing table.
existing_columns = db.execute('PRAGMA table_info(articles)').fetchall()
if not any(col[1] == 'description' for col in existing_columns):
    db.execute('ALTER TABLE articles ADD COLUMN description TEXT')

# api/news always sorts on published_date -- without this, every request
# sorts the whole table.
db.execute('CREATE INDEX IF NOT EXISTS articlesByPublishedDate ON articles (published_date)')
db.commit()

# 3. SQL to insert without duplication into the DB. The url UNIQUE
# constraint catches a re-fetched article; DUPLICATE_TITLE_SQL catches the
# same article republished under a second URL (e.g. NASA's doubled APODs).
INSERT_ARTICLE_SQL = '''
    INSERT OR IGNORE INTO articles (source, title, url, published_date, description)
    VALUES (?, ?, ?, ?, ?)
'''
DUPLICATE_TITLE_SQL = 'SELECT 1 FROM articles WHERE source = ? AND title = ? LIMIT 1'

# 4. List of space industry RSS feeds -- kept identical to readNews.js,
# including its existing duplicate 'ESA EO' entry and the stray leading tab
# in the 'ESA Spaceflight' URL; not "fixed" here since this is meant to be
# a faithful behavioural port, not a data cleanup pass.
FEEDS = [
    {'name': 'SpaceNews', 'url': 'https://spacenews.com/feed'},
    {'name': 'Spaceflight Now', 'url': 'https://spaceflightnow.com/feed'},
    {'name': 'SpaceQ', 'url': 'https://spaceq.ca/feed'},
    {'name': 'Space.com', 'url': 'https://www.space.com/feeds.xml'},
    {'name': 'Universe Today', 'url': 'https://www.universetoday.com/feed'},
    {'name': 'NASA News', 'url': 'https://www.nasa.gov/feed/'},
    {'name': 'Ars Technica Space', 'url': 'https://arstechnica.com/space/feed/'},
    {'name': 'ESA Space News', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Space_News'},
    {'name': 'ESA EO', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Observing_the_Earth'},
    {'name': 'ESA Spaceflight', 'url': '\thttp://www.esa.int/rssfeed/Our_Activities/Human_Spaceflight'},
    {'name': 'ESA EO', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Observing_the_Earth'},
    {'name': 'ESA Launchers', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Launchers'},
    {'name': 'ESA Navigation', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Navigation'},
    {'name': 'ESA Science', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Space_Science'},
    {'name': 'ESA Engineering', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Space_Engineering_Technology'},
    {'name': 'ESA Operations', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Operations'},
    {'name': 'ESA Comms', 'url': 'http://www.esa.int/rssfeed/Our_Activities/Telecommunications_Integrated_Applications'},
    {'name': 'US Space Force', 'url': 'https://www.spaceforce.mil/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=1060'},
]

# 5. RSS XML parser with no external dependencies (mirrors readNews.js's
# own regex-based approach exactly, including its reliance on [\s\S] to
# match across newlines -- Python's re module treats that character class
# the same way JS does, no re.DOTALL flag needed).

NAMED_ENTITIES = {
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
    '&quot;': '"',
    '&apos;': "'",
}


def decode_entities(text):
    if not text:
        return text
    text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    for entity, char in NAMED_ENTITIES.items():
        text = text.replace(entity, char)
    return text


def strip_cdata_wrapper(raw):
    trimmed = raw.strip()
    cdata_match = re.match(r'^<!\[CDATA\[([\s\S]*)\]\]>$', trimmed)
    return cdata_match.group(1) if cdata_match else trimmed


def extract_summary(html):
    if not html:
        return None
    plain_text = decode_entities(strip_cdata_wrapper(html))
    plain_text = re.sub(r'<[^>]*>', ' ', plain_text)
    plain_text = re.sub(r'\s+', ' ', plain_text).strip()
    return plain_text or None


# RSS <pubDate> arrives as RFC 2822 text (e.g. "Wed, 29 Jul 2026
# 23:15:30 +0000"). Storing that raw string (as this used to do) breaks
# SQL-level chronological sorting -- ORDER BY on it is a plain string
# comparison, and since the string starts with the weekday name, sort
# order scrambles across day/month boundaries (confirmed live: "Thu, 30
# Jul" sorts before "Wed, 29 Jul" alphabetically, despite being later).
# Normalizing to ISO 8601 here makes both SQL's ORDER BY and any
# client-side new Date(...) parse give the same, actually-correct answer.
def normalize_pubdate_to_iso(raw_date):
    if not raw_date:
        return None
    try:
        parsed = parsedate_to_datetime(raw_date)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except (TypeError, ValueError):
        return None


def parse_rss_feed(xml_text):
    articles = []
    for item_match in re.finditer(r'<item>([\s\S]*?)</item>', xml_text):
        item_content = item_match.group(1)

        title_match = re.search(r'<title>([\s\S]*?)</title>', item_content)
        link_match = re.search(r'<link>([\s\S]*?)</link>', item_content)
        date_match = re.search(r'<pubDate>([\s\S]*?)</pubDate>', item_content)
        description_match = re.search(r'<description>([\s\S]*?)</description>', item_content)
        content_encoded_match = re.search(r'<content:encoded>([\s\S]*?)</content:encoded>', item_content)

        if title_match and link_match:
            # Prefer <description> (usually a genuine teaser); fall back to
            # <content:encoded> only for feeds that omit description entirely.
            if description_match:
                summary_source = description_match.group(1)
            elif content_encoded_match:
                summary_source = content_encoded_match.group(1)
            else:
                summary_source = None

            raw_date = date_match.group(1).strip() if date_match else None
            articles.append({
                'title': decode_entities(strip_cdata_wrapper(title_match.group(1))),
                'url': decode_entities(strip_cdata_wrapper(link_match.group(1))),
                'date': normalize_pubdate_to_iso(raw_date) or 'Unknown Date',
                'description': extract_summary(summary_source),
            })
    return articles


# 6. Sequential engine to parse and store items for each RSS feed
def fetch_all_feeds():
    """Returns the number of new articles stored, across every feed."""
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Starting Space Feed Sync ===')

    totalNewArticles = 0
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    for feed in FEEDS:
        print(f'Processing: {feed["name"]}...')

        try:
            request = urllib.request.Request(feed['url'], headers={'User-Agent': 'Mozilla/5.0 (compatible; LCARS-FAS/1.0)'})
            with urllib.request.urlopen(request) as response:
                if response.status >= 400:
                    raise Exception(f'HTTP Error Status: {response.status}')
                xml_data = response.read().decode('utf-8', errors='replace')

            all_articles = parse_rss_feed(xml_data)

            if len(all_articles) == 0:
                print('No valid items found. Skipping.')
                continue

            # Filter targeting elements exclusively from the last 7 days.
            # article['date'] is already ISO 8601 by this point (see
            # normalize_pubdate_to_iso() / parse_rss_feed() above), not the
            # raw RFC 2822 pubDate text, so this parses with fromisoformat()
            # rather than parsedate_to_datetime().
            articles_within_last_week = []
            for article in all_articles:
                try:
                    pub_dt = datetime.fromisoformat(article['date'])
                    if pub_dt >= one_week_ago:
                        articles_within_last_week.append(article)
                except (TypeError, ValueError):
                    continue

            # Determine the maximum item yield strategy -- matches
            # readNews.js exactly, including that the >=100 branch takes
            # the top 100 of allArticles (unfiltered by date), not the top
            # 100 of articlesWithinLastWeek.
            if len(articles_within_last_week) < 100:
                articles_to_insert = articles_within_last_week
                print(f'Selecting ({len(articles_within_last_week)} articles from within the last week).')
            else:
                articles_to_insert = all_articles[:100]
                print(f' -> Adding just the top 100 articles from within the last week out of {len(articles_within_last_week)}) articles in total.')

            new_items_count = 0
            fillerSkipped = 0
            duplicatesSkipped = 0

            # Commit items to database -- filler (see fillerRules.py) is
            # dropped here and never stored.
            for article in articles_to_insert:
                if classifyFiller(feed['name'], article['title']):
                    fillerSkipped += 1
                    continue
                if db.execute(DUPLICATE_TITLE_SQL, (feed['name'], article['title'])).fetchone():
                    duplicatesSkipped += 1
                    continue
                cursor = db.execute(INSERT_ARTICLE_SQL, (
                    feed['name'], article['title'], article['url'], article['date'], article['description'],
                ))
                if cursor.rowcount > 0:
                    new_items_count += 1
            db.commit()
            totalNewArticles += new_items_count

            print(f' -> Done. Added {new_items_count} brand new articles, '
                  f'skipped {fillerSkipped} filler, {duplicatesSkipped} duplicate titles.\n')
        except Exception as error:
            print(f' -> Error synchronizing {feed["name"]}: {error}\n')

        # Add 1-second operational delay so as not to irritate the RSS servers
        time.sleep(1)

    now = datetime.now()
    print(f'=== ALL RSS SPACE FEEDS SYNCHED WITH LOCAL DB AT {now.strftime("%m/%d/%Y")} {now.strftime("%H:%M:%S")} ===\n')
    return totalNewArticles


# 7. Run once and exit -- scheduling (every 30 minutes) is owned by cron,
# not this script. See readNews.js's own self-looping version for the
# original design this was ported from; that shape suits a persistent
# process, not a cron-invoked one, so it was dropped here deliberately.
if __name__ == '__main__':
    # Recorded in ingestionRuns for the landing page's data-freshness table;
    # "changes" is the number of new articles stored this run.
    with trackRun(db, 'news') as run:
        run.changes = fetch_all_feeds()

        # Housekeeping after every fetch: drop filler/duplicates/anything older
        # than six months, re-tag every article for the news filter buttons
        # (so topicRules.py changes reach old articles too), then reclaim the
        # space the deletes freed.
        pruneCounts = pruneNews(db)
        print(f'Pruned: {pruneCounts or "nothing"}')
        retagAllArticles(db)
    vacuumDatabase(db)
