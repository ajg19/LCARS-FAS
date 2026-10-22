"""Tests for scripts/readNews.py's feed parsing -- the part of news
ingestion the filler/topic/prune tests (test_newsRules.py) don't reach --
and its database set-up. A sample feed in the shape the 18 RSS sources
send; no network, and never the real databases/ingestionNews.db."""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import readNews as rn  # noqa: E402

FEED = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Sample Space Feed</title>
  <item>
    <title><![CDATA[Ariane 6 & Vega-C: launch update]]></title>
    <link>https://example.test/news/ariane-6?a=1&amp;b=2</link>
    <pubDate>Wed, 21 Oct 2026 23:15:30 +0000</pubDate>
    <description><![CDATA[<p>The <b>second</b> flight of the year&#8230;   more soon.</p>]]></description>
    <content:encoded><![CDATA[<p>Full article text that should not be used.</p>]]></content:encoded>
  </item>
  <item>
    <title>Sentinel-1D &#x2014; first images</title>
    <link><![CDATA[https://example.test/news/s1d]]></link>
    <pubDate>Tue, 20 Oct 2026 08:00:00 GMT</pubDate>
    <content:encoded><![CDATA[<div>Only <i>content:encoded</i> here.</div>]]></content:encoded>
  </item>
  <item>
    <title>No date, no summary</title>
    <link>https://example.test/news/nodate</link>
  </item>
  <item>
    <title>An item without a link is skipped</title>
    <pubDate>Tue, 20 Oct 2026 08:00:00 GMT</pubDate>
  </item>
</channel>
</rss>'''


def test_parse_feed_extracts_every_linked_item():
    articles = rn.parse_rss_feed(FEED)
    assert [a['title'] for a in articles] == ['Ariane 6 & Vega-C: launch update', 'Sentinel-1D — first images',
                                             'No date, no summary']


def test_cdata_entities_and_dates():
    first, second, third = rn.parse_rss_feed(FEED)
    assert first['url'] == 'https://example.test/news/ariane-6?a=1&b=2'
    assert first['date'] == '2026-10-21T23:15:30+00:00'
    assert second['url'] == 'https://example.test/news/s1d'
    assert second['date'] == '2026-10-20T08:00:00+00:00'
    assert third['date'] == 'Unknown Date'


def test_description_preferred_over_content_encoded_and_cleaned():
    first, second, third = rn.parse_rss_feed(FEED)
    assert first['description'] == 'The second flight of the year… more soon.'
    assert second['description'] == 'Only content:encoded here.'
    assert third['description'] is None


def test_no_items_gives_nothing():
    assert rn.parse_rss_feed('<rss><channel><title>x</title></channel></rss>') == []


def test_decode_entities():
    assert rn.decode_entities('A &amp; B &lt;C&gt; &quot;D&quot; &apos;E&apos;') == 'A & B <C> "D" \'E\''
    assert rn.decode_entities('&#169; &#x00E9;') == '© é'
    assert rn.decode_entities(None) is None


def test_strip_cdata_wrapper():
    assert rn.strip_cdata_wrapper('  <![CDATA[hello]]>  ') == 'hello'
    assert rn.strip_cdata_wrapper('plain') == 'plain'


def test_pubdate_normalisation():
    assert rn.normalize_pubdate_to_iso('Thu, 22 Oct 2026 01:02:03 +0200') == '2026-10-22T01:02:03+02:00'
    assert rn.normalize_pubdate_to_iso('Thu, 22 Oct 2026 01:02:03 -0000') == '2026-10-22T01:02:03+00:00'
    assert rn.normalize_pubdate_to_iso('not a date') is None
    assert rn.normalize_pubdate_to_iso(None) is None


def test_iso_dates_sort_chronologically_where_rfc_dates_did_not():
    # The reason for normalising: "Thu, 30 Jul" sorts before "Wed, 29 Jul" as text.
    later = rn.normalize_pubdate_to_iso('Thu, 30 Jul 2026 00:00:00 +0000')
    earlier = rn.normalize_pubdate_to_iso('Wed, 29 Jul 2026 00:00:00 +0000')
    assert earlier < later


def test_open_db_creates_schema(tmp_path):
    db = rn.openDb(str(tmp_path / 'news.db'))
    columns = [row[1] for row in db.execute('PRAGMA table_info(articles)')]
    assert 'description' in columns and 'published_date' in columns
    indexes = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")]
    assert 'articlesByPublishedDate' in indexes
    db.close()


def test_open_db_adds_description_to_an_old_table(tmp_path):
    path = str(tmp_path / 'old.db')
    old = sqlite3.connect(path)
    old.execute('CREATE TABLE articles (id INTEGER PRIMARY KEY, source TEXT, title TEXT, url TEXT UNIQUE, '
                'published_date TEXT, fetched_at DATETIME)')
    old.commit()
    old.close()
    db = rn.openDb(path)
    assert 'description' in [row[1] for row in db.execute('PRAGMA table_info(articles)')]
    db.close()
