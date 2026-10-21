"""Rebuilds the articleTopics table -- which news filter buttons each
article appears under -- from topicRules.classifyTopics(), and the
newsTopicCounts table the control panel histogram reads.

readNews.py calls retagAllArticles() on every run, so a change to
topicRules.py applies to every stored article, old and new, within 30
minutes. Run by hand to apply a rule change immediately, or to tag a
database for the first time:

    python scripts/tagNews.py
"""

import sqlite3
import sys

from topicRules import classifyTopics

from dbPaths import NEWS_DB, dbPath
DB_PATH = dbPath(NEWS_DB)


def ensureTopicsTable(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS articleTopics (
            articleID INTEGER NOT NULL,
            topic     TEXT NOT NULL,
            PRIMARY KEY (articleID, topic)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS articleTopicsByTopic ON articleTopics (topic)')
    # Per-topic article totals for the control panel histogram, stored
    # rather than counted on every page load -- see storeTopicCounts().
    db.execute('''
        CREATE TABLE IF NOT EXISTS newsTopicCounts (
            topic        TEXT PRIMARY KEY,
            articleCount INTEGER NOT NULL,
            updatedAt    TEXT NOT NULL
        )
    ''')
    db.commit()


def storeTopicCounts(db):
    """Rewrites newsTopicCounts from articleTopics, plus an 'all' row for
    the total number of articles. Called whenever articleTopics changes."""
    db.execute('DELETE FROM newsTopicCounts')
    db.execute('''
        INSERT INTO newsTopicCounts (topic, articleCount, updatedAt)
        SELECT topic, COUNT(*), datetime('now') FROM articleTopics GROUP BY topic
    ''')
    db.execute('''
        INSERT INTO newsTopicCounts (topic, articleCount, updatedAt)
        SELECT 'all', COUNT(*), datetime('now') FROM articles
    ''')
    db.commit()


def retagAllArticles(db):
    """Clears and rebuilds every article's topics. Returns {topic: count}."""
    ensureTopicsTable(db)
    db.execute('DELETE FROM articleTopics')
    counts = {}
    rows = db.execute('SELECT id, source, title, description FROM articles').fetchall()
    for articleID, source, title, description in rows:
        for topic in classifyTopics(source, title, description):
            db.execute('INSERT INTO articleTopics (articleID, topic) VALUES (?, ?)', (articleID, topic))
            counts[topic] = counts.get(topic, 0) + 1
    db.commit()
    storeTopicCounts(db)
    return counts


if __name__ == '__main__':
    db = sqlite3.connect(DB_PATH)
    counts = retagAllArticles(db)
    db.close()
    for topic in sorted(counts):
        print(f'{topic:<14}{counts[topic]}')
