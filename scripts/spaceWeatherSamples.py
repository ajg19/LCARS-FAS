"""Shared by the space-weather ingestion scripts (ingestionSWPC.py,
ingestionGFZ.py, ingestionDONKI.py): the two tables they all write, the
upserts, the retention helpers and a polite fetcher.
(0_documentation/plans/spaceWeatherIngestionPlan.md, sections 4 and 5.)

  samples  one row per (series, tsUtc): a number, its unit and a quality
           note. A missing reading is NULL, never -999 or 'N/A'. Written
           by upsert, so a re-run changes nothing.
  events   one row per (eventType, eventID): when it started and the
           source's own record as JSON.
  latestMaps  one row per map name: only the newest map, trimmed to a small
           grid (JSON), for the website. Replaced, never accumulated.

Times are UTC ISO text with a Z ('2026-10-24T15:03:00Z'), so they sort
and group as text.

Retention (plan section 4): the 1-minute series -- the L1 magnetic field
and plasma (series names starting 'l1') and the GOES X-ray flux
('goesXray') -- are kept LIVE_DAYS (90) days at full resolution, then
DELETED (pruneOldOneMinute; no hourly means, no archive). Everything else
is kept in full. Run daily by ingestionSWPC.py --job swpcPrune.
"""

import json
import random
import sqlite3
import time
from datetime import datetime, timedelta

from common import httpGet

LIVE_DAYS = 90
ONE_MINUTE_PREFIXES = ('l1', 'goesXray')

# Gap between two requests to one source, as a person clicking about would leave.
MIN_GAP_SEC, MAX_GAP_SEC = 2, 5

SAMPLES_SQL = '''
    CREATE TABLE IF NOT EXISTS samples (
        series  TEXT NOT NULL,
        tsUtc   TEXT NOT NULL,
        value   REAL,
        unit    TEXT,
        quality TEXT,
        PRIMARY KEY (series, tsUtc)
    ) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS events (
        eventType TEXT NOT NULL,
        startUtc  TEXT,
        eventID   TEXT NOT NULL,
        json      TEXT NOT NULL,
        PRIMARY KEY (eventType, eventID)
    ) WITHOUT ROWID;
    CREATE INDEX IF NOT EXISTS eventsByStart ON events (eventType, startUtc);
    CREATE TABLE IF NOT EXISTS latestMaps (
        name  TEXT PRIMARY KEY,
        tsUtc TEXT NOT NULL,
        json  TEXT NOT NULL
    ) WITHOUT ROWID;
'''


class FeedError(Exception):
    """A feed's shape is not what we validated against. The whole feed is
    rejected: nothing from it is stored."""


def openTables(db):
    """Creates samples and events if they are not there."""
    db.executescript(SAMPLES_SQL)
    db.commit()


# --- Times --------------------------------------------------------------------

TIME_FORMATS = ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%MZ', '%Y-%m-%d_%H:%M', '%Y-%m-%d')


def utcText(text):
    """'2026-10-17T02:48Z', '2026-10-24T09:07:00', '2026-10-24_00:05' or a
    bare date -> '2026-10-17T02:48:00Z'. FeedError for anything else."""
    for form in TIME_FORMATS:
        try:
            return datetime.strptime(str(text).strip(), form).strftime('%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            continue
    raise FeedError(f'unreadable time {text!r}')


def loadJson(text):
    try:
        return json.loads(text)
    except ValueError as error:
        raise FeedError(f'not JSON: {error}')


def number(value, what, allowText=False):
    """A float, or None for a missing reading (JSON null, or text that is
    empty). Booleans and, unless allowText, strings are a surprise."""
    if value is None or (allowText and isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise FeedError(f'{what}: expected a number, got {value!r}')
    if isinstance(value, (int, float)):
        return float(value)
    if allowText and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
    raise FeedError(f'{what}: expected a number, got {value!r}')


# --- Upserts ------------------------------------------------------------------

UPSERT_SAMPLE_SQL = '''
    INSERT INTO samples (series, tsUtc, value, unit, quality) VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(series, tsUtc) DO UPDATE SET
        value = excluded.value, unit = excluded.unit, quality = excluded.quality
    WHERE (excluded.value IS NOT samples.value OR excluded.unit IS NOT samples.unit
           OR excluded.quality IS NOT samples.quality)
      AND (? IS NULL OR samples.quality IS NOT ? OR excluded.quality IS ?)
'''

UPSERT_EVENT_SQL = '''
    INSERT INTO events (eventType, startUtc, eventID, json) VALUES (?, ?, ?, ?)
    ON CONFLICT(eventType, eventID) DO UPDATE SET startUtc = excluded.startUtc, json = excluded.json
    WHERE excluded.json IS NOT events.json OR excluded.startUtc IS NOT events.startUtc
'''


def upsertSamples(db, rows, finalQuality=None):
    """rows: (series, tsUtc, value, unit, quality). Returns the number of
    rows new or changed. A row repeated within `rows` counts once (the last
    wins). With finalQuality (e.g. 'def'), a stored row of that quality is
    never replaced by a row of another: a provisional value cannot undo a
    definitive one."""
    latest = {(r[0], r[1]): r for r in rows}
    changes = 0
    with db:
        for series, tsUtc, value, unit, quality in latest.values():
            cursor = db.execute(UPSERT_SAMPLE_SQL, (series, tsUtc, value, unit, quality,
                                                    finalQuality, finalQuality, finalQuality))
            changes += cursor.rowcount
    return changes


def upsertEvents(db, rows):
    """rows: (eventType, startUtc, eventID, record). The record is stored
    as JSON with sorted keys. Returns the number new or changed."""
    latest = {(r[0], r[2]): r for r in rows}
    changes = 0
    with db:
        for eventType, startUtc, eventID, record in latest.values():
            cursor = db.execute(UPSERT_EVENT_SQL, (eventType, startUtc, eventID,
                                                   json.dumps(record, sort_keys=True, ensure_ascii=False)))
            changes += cursor.rowcount
    return changes


def upsertMap(db, name, tsUtc, record):
    """Replaces the stored map `name` with `record` (JSON-able) if tsUtc is
    not older than the one held. Returns 1 if stored or changed, else 0."""
    text = json.dumps(record, separators=(',', ':'), sort_keys=True)
    with db:
        held = db.execute('SELECT tsUtc, json FROM latestMaps WHERE name = ?', (name,)).fetchone()
        if held and (held[0] > tsUtc or (held[0] == tsUtc and held[1] == text)):
            return 0
        db.execute('INSERT OR REPLACE INTO latestMaps (name, tsUtc, json) VALUES (?, ?, ?)', (name, tsUtc, text))
    return 1


def storeFeed(db, samples=(), events=(), finalQuality=None, maps=()):
    """One feed's validated rows into the database. maps: (name, tsUtc,
    record). Returns changes."""
    return (upsertSamples(db, samples, finalQuality) + upsertEvents(db, events)
            + sum(upsertMap(db, name, ts, record) for name, ts, record in maps))


# --- Retention ----------------------------------------------------------------

def isOneMinuteSeries(series):
    return series.startswith(ONE_MINUTE_PREFIXES)


def liveCutoff(now, days=LIVE_DAYS):
    """The time before which 1-minute rows have outlived their live window,
    as UTC text on the hour, from `now` (a datetime or UTC text)."""
    if isinstance(now, str):
        now = datetime.strptime(utcText(now), '%Y-%m-%dT%H:%M:%SZ')
    return (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:00:00Z')


def pruneOldOneMinute(db, now, days=LIVE_DAYS):
    """Deletes the 1-minute rows (L1, GOES X-ray) older than `days` before
    `now`, in one transaction. Nothing is kept in their place. Returns
    {series: rows removed} for the series that lost rows."""
    cutoff = liveCutoff(now, days)
    removed = {}
    with db:
        names = [r[0] for r in db.execute('SELECT DISTINCT series FROM samples')]
        for name in names:
            if isOneMinuteSeries(name):
                count = db.execute('DELETE FROM samples WHERE series = ? AND tsUtc < ?', (name, cutoff)).rowcount
                if count:
                    removed[name] = count
    return removed


# --- Fetching -----------------------------------------------------------------

class PacedFetcher:
    """Callable url -> body text for the ingestion scripts' `fetch`
    argument. Asks for gzip, leaves a random 2 to 5 s between requests,
    and raises on an HTTP error or an empty body. Tests pass their own
    function instead and never reach this."""

    def __init__(self, sleep=time.sleep, headers=None):
        self.sleep, self.headers, self.count = sleep, headers or {}, 0

    def __call__(self, url):
        if self.count:
            self.sleep(random.uniform(MIN_GAP_SEC, MAX_GAP_SEC))
        self.count += 1
        status, text = httpGet(url, {'Accept-Encoding': 'gzip', **self.headers})
        if status >= 400:
            raise Exception(f'HTTP {status}')
        if not text.strip():
            raise Exception('empty response')
        return text


def connect(path):
    """A WAL connection with the shared tables, for a space-weather
    ingestion database."""
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode = WAL')
    openTables(db)
    return db
