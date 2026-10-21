"""Unit tests for the news filler/topic rules and the prune/tag
housekeeping in scripts/ -- run against a throwaway in-memory database,
never the real databases/space_news.db.

Run with:  pytest 0_tests/ -v
"""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
from fillerRules import classifyFiller  # noqa: E402
from pruneNews import pruneNews, vacuumDatabase  # noqa: E402
from tagNews import retagAllArticles  # noqa: E402
from topicRules import classifyTopics  # noqa: E402


# --- Filler rules --------------------------------------------------------
# Real titles from the feeds.

@pytest.mark.parametrize('source, title, expectedRule', [
    ('Space.com', ' Heat shield under fire | Space photo of the day for Aug. 26, 2026 ', 'dailyFeatures'),
    ('Space.com', ' On this day in space! Aug. 24, 2006: Pluto loses its planet status ', 'dailyFeatures'),
    ('NASA News', 'APOD: 2026 August 26 – JWST Images The Lion’s Head Nebula', 'dailyFeatures'),
    ('Space.com', ' This Week In Space podcast: Episode 224 – The Science of Artemis ', 'dailyFeatures'),
    ('NASA News', 'JOB OPPORTUNITIES: NASA OFFICE OF THE GENERAL COUNSEL', 'nasaAdmin'),
    ('NASA News', 'TB 26-04 Webbings for Use in Elevated Oxygen Environments', 'nasaAdmin'),
    ('NASA News', 'NASA Invites Media to LunaRecycle Challenge Finale Event in Alabama', 'nasaAdmin'),
    ('Space.com', " 'Star Wars: Zero Company' review: XCOM-like strategically recaptures the magic ", 'entertainment'),
    ('Space.com', " 'Ghosts of Mars' at 25: Are we any closer to living on the Red Planet? ", 'entertainment'),
    ('Space.com', ' Stream \'Star Trek: Strange New Worlds\' and \'Silo\' securely with 87% off Surfshark VPN ', 'entertainment'),
    ('Space.com', ' At 25% off, this beginner-friendly Celestron telescope will bring the lunar eclipse closer ', 'shopping'),
    ('Space.com', ' I bought a $50 telescope on Facebook Marketplace – here\'s what I learned ', 'shopping'),
])
def test_filler_is_caught(source, title, expectedRule):
    assert classifyFiller(source, title) == expectedRule


@pytest.mark.parametrize('source, title', [
    ('SpaceNews', 'Hughes files for bankruptcy after GEO business loses ground to Starlink'),
    ('Ars Technica Space', 'Rocket Report: SpaceX makes its mark on the Moon; ULA names new boss'),
    ('ESA Space News', 'Week in images: 17-21 August 2026'),
    ('Space.com', ' Rocket Lab to start launching missile-defense missions from Alaska under $266 million Space Force deal '),
    ('Space.com', ' Mars dust is toxic. How will future astronauts deal with it? '),
    ('Space.com', ' Inside the Nancy Grace Roman Space Telescope, NASA\'s next great observatory '),
    ('SpaceNews', 'A review of NASA\'s commercial crew program'),  # "review" only counts on Space.com
    ('NASA News', None),
])
def test_real_news_is_kept(source, title):
    assert classifyFiller(source, title) is None


# --- Topic rules ---------------------------------------------------------

def test_article_can_have_several_topics():
    topics = classifyTopics('Space.com', 'SpaceX launches 3 BlueBird satellites on Falcon 9', '')
    assert 'launch' in topics and 'onOrbit' in topics


def test_space_force_base_names_are_not_defence():
    topics = classifyTopics('Spaceflight Now', 'SpaceX launches 24 Starlink satellites',
                            'Liftoff from Vandenberg Space Force Base in California.')
    assert 'defence' not in topics


def test_space_force_itself_is_defence():
    assert 'defence' in classifyTopics('SpaceNews', 'Space Force picks 15 companies for training range', '')


@pytest.mark.parametrize('title, description', [
    ('K2 Space raises $500 million for commercial, defense satellite expansion', ''),
    ('Intermap signs $11 million deal to acquire remaining PCI Geomatics shares', ''),
    ('Rocketdyne reemerges as standalone space company',
     'AE Industrial private-equity firm takes 60% stake as L3Harris retains a noncontrolling interest'),
    ('Hughes files for bankruptcy after GEO business loses ground to Starlink', ''),
])
def test_finance_is_tagged(title, description):
    assert 'finance' in classifyTopics('SpaceNews', title, description)


@pytest.mark.parametrize('title, description', [
    ('Space Force outlines acquisition wins amid Department wide transformation', ''),
    ('Defence Investment Agency awards Telesat a major Arctic security contract', ''),
    ('SpaceX is set to acquire 130,000 acres of marshland in southern Louisiana', ''),
    ("NASA's Perseverance Rover Watches Earth Vanish Behind Martian Moon",
     'The images were acquired by the rover on Sol 1234.'),
    ('In Defence of Canada briefing: Spaceport polling', 'New investments in Arctic resilience.'),
])
def test_finance_lookalikes_are_not_finance(title, description):
    assert 'finance' not in classifyTopics('SpaceNews', title, description)


def test_source_topics_apply_whatever_the_wording():
    assert 'eo' in classifyTopics('ESA EO', 'Guinea-Bissau Tidal Waters', '')


def test_untagged_article_is_other():
    assert classifyTopics('NASA News', 'Louisiana Students Loft Payloads', '') == ['other']


# --- Prune and tag, on a throwaway database ------------------------------

@pytest.fixture
def newsDB():
    db = sqlite3.connect(':memory:')
    db.execute('''
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, title TEXT, url TEXT UNIQUE, published_date TEXT,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP, description TEXT
        )
    ''')
    rows = [
        ('SpaceNews', 'Telesat lands defense contract', 'u1', "date('now')", "datetime('now')"),
        ('Space.com', 'Heat shield | Space photo of the day for Aug. 26', 'u2', "date('now')", "datetime('now')"),
        ('NASA News', 'NASA Begins Plume Tests', 'u3', "date('now')", "datetime('now')"),
        ('NASA News', 'NASA Begins Plume Tests', 'u4', "date('now')", "datetime('now')"),
        ('SpaceNews', 'Ancient launch story', 'u5', "date('now', '-7 months')", "datetime('now', '-7 months')"),
        ('SpaceNews', 'Undated old story', 'u6', "'Unknown Date'", "datetime('now', '-7 months')"),
        ('SpaceNews', 'Undated new story', 'u7', "'Unknown Date'", "datetime('now')"),
    ]
    for source, title, url, published, fetched in rows:
        db.execute(f'INSERT INTO articles (source, title, url, published_date, fetched_at) '
                   f'VALUES (?, ?, ?, {published}, {fetched})', (source, title, url))
    db.commit()
    return db


def remainingTitles(db):
    return sorted(title for (title,) in db.execute('SELECT title FROM articles'))


def test_prune_deletes_filler_duplicates_and_old(newsDB):
    counts = pruneNews(newsDB)
    assert counts == {'dailyFeatures': 1, 'duplicate': 1, 'older than 6 months': 2}
    assert remainingTitles(newsDB) == ['NASA Begins Plume Tests', 'Telesat lands defense contract', 'Undated new story']


def test_prune_keeps_the_earliest_of_duplicates(newsDB):
    pruneNews(newsDB)
    assert newsDB.execute("SELECT url FROM articles WHERE title = 'NASA Begins Plume Tests'").fetchall() == [('u3',)]


def test_prune_dry_run_changes_nothing(newsDB):
    counts = pruneNews(newsDB, dryRun=True)
    assert sum(counts.values()) == 4
    assert newsDB.execute('SELECT COUNT(*) FROM articles').fetchone()[0] == 7


def test_prune_months_override(newsDB):
    counts = pruneNews(newsDB, months=12, dryRun=True)
    assert 'older than 12 months' not in counts


def test_retag_then_prune_leaves_no_orphan_topics(newsDB):
    retagAllArticles(newsDB)
    pruneNews(newsDB)
    orphans = newsDB.execute(
        'SELECT COUNT(*) FROM articleTopics WHERE articleID NOT IN (SELECT id FROM articles)'
    ).fetchone()[0]
    assert orphans == 0


def test_retag_tags_every_article(newsDB):
    retagAllArticles(newsDB)
    untagged = newsDB.execute(
        'SELECT COUNT(*) FROM articles WHERE id NOT IN (SELECT articleID FROM articleTopics)'
    ).fetchone()[0]
    assert untagged == 0
    assert ('defence',) in newsDB.execute(
        "SELECT topic FROM articleTopics WHERE articleID = 1").fetchall()


def storedCounts(db):
    return dict(db.execute('SELECT topic, articleCount FROM newsTopicCounts').fetchall())


def test_retag_stores_topic_counts(newsDB):
    retagAllArticles(newsDB)
    stored = storedCounts(newsDB)
    actual = dict(newsDB.execute('SELECT topic, COUNT(*) FROM articleTopics GROUP BY topic').fetchall())
    assert {topic: n for topic, n in stored.items() if topic != 'all'} == actual
    assert stored['all'] == 7


def test_prune_keeps_stored_counts_in_step(newsDB):
    retagAllArticles(newsDB)
    pruneNews(newsDB)
    assert storedCounts(newsDB)['all'] == 3


def test_vacuum_runs(newsDB):
    pruneNews(newsDB)
    assert vacuumDatabase(newsDB) is True
