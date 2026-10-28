"""LCARS backend -- Python port of server.js.

Faithful, endpoint-by-endpoint port: same URL paths, same query params, same
JSON response shapes, same static-file fallback behaviour (including its
existing quirk of defaulting to text/html for any extension it doesn't
recognise, e.g. images/fonts -- preserved as-is rather than "fixed" during
the port, since this is meant to be a behavioural match, not a rewrite).

Written as a single WSGI `application` callable so the exact same code runs
two ways with no changes: standalone locally via wsgiref (mirrors `node
server.js`'s UX -- just run this file, get a dev server on port 3000), and
under Passenger in production (the callable Passenger's own generated
passenger_wsgi.py wrapper imports directly).

All paths are anchored to this script's own directory (os.path.dirname(
os.path.abspath(__file__)), the Python equivalent of __dirname), not the
process's working directory -- same reasoning as the __dirname fix on the
Node side: must not matter where this is launched from.
"""

import gzip
import hashlib
import json
import math
import mimetypes
import os
import pathlib
import re
import random
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs

PORT = 3000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# scripts/ holds dbPaths.py, the one place database paths and names live.
sys.path.append(os.path.join(BASE_DIR, 'scripts'))
import dbPaths  # noqa: E402
import visitCounter  # noqa: E402
from dbPaths import (BUG_REPORTS_DB, GCAT_DB, GROUND_SEGMENT_DB, NEWS_DB,  # noqa: E402
                     ORBITAL_DB, SITE_GROUND_SEGMENT_DB, SITE_NEWS_DB, SITE_ORBITAL_DB, SITE_SKY_DB, SITE_WEATHER_DB,
                     SKY_DB, STATS_DB)

DB_DIR = dbPaths.DB_DIR


def open_db(filename, read_only=False):
    path = dbPaths.dbPath(filename)
    if read_only:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# The website's databases (0_documentation/plans/dbRefactorPlan.md, step 10):
# one site<Type>.db per kind of data, each built and swapped in whole by
# scripts/publishSite.py. site_db(kind) hands out a read-only connection,
# one per thread, and reopens it whenever the file has been replaced
# (inode, mtime or size changed) -- so a publish is picked up on the next
# request, and a request never sees half a file.
#
# Until the live server is migrated (step 12) it has no site files. A kind
# whose site file doesn't exist is served from the pre-refactor databases
# instead, opened together (the first as main, the rest attached) so the
# same unqualified table names resolve -- master stays deployable.
#
# On Windows (the DEV box) an open connection stops publishSite.py
# replacing the file, so there each thread's connections are closed after
# every request (release_site_dbs, called by application()).
SITE_FILES = {
    'orbital': SITE_ORBITAL_DB,
    'news': SITE_NEWS_DB,
    'sky': SITE_SKY_DB,
    'groundSegment': SITE_GROUND_SEGMENT_DB,
    'weather': SITE_WEATHER_DB,
}
LEGACY_FILES = {
    'orbital': (ORBITAL_DB, STATS_DB, GCAT_DB),
    'news': (NEWS_DB,),
    'sky': (SKY_DB,),
    'groundSegment': (GROUND_SEGMENT_DB,),
    'weather': (),   # new with the space-weather work: no pre-refactor file to fall back to
}
RELEASE_AFTER_REQUEST = os.name == 'nt'
_site_conns = threading.local()


def site_files(kind):
    """(paths, legacy) -- the files serving `kind` right now."""
    path = dbPaths.dbPath(SITE_FILES[kind])
    if os.path.exists(path):
        return [path], False
    return [p for p in (dbPaths.dbPath(name) for name in LEGACY_FILES[kind]) if os.path.exists(p)], True


def site_version(kind):
    """Identifies the current content of `kind`'s files: changes whenever
    one is replaced or rewritten."""
    paths, _ = site_files(kind)
    if not paths:
        raise FileNotFoundError(f'no database for {kind}')
    return tuple((p, st.st_ino, st.st_mtime_ns, st.st_size) for p, st in ((p, os.stat(p)) for p in paths))


def site_db(kind):
    """Read-only connection for `kind` ('orbital', 'news', 'sky',
    'groundSegment'), or None when no database for it exists yet."""
    conns = _site_conns.__dict__.setdefault('conns', {})
    try:
        version = site_version(kind)
    except FileNotFoundError:
        return None
    held = conns.get(kind)
    if held is not None and held[0] == version:
        return held[1]
    if held is not None:
        held[1].close()
    paths = [entry[0] for entry in version]
    conn = sqlite3.connect(f'file:{paths[0]}?mode=ro', uri=True)
    for index, path in enumerate(paths[1:]):
        conn.execute(f'ATTACH DATABASE ? AS legacy{index}', (f'file:{path}?mode=ro',))
    conn.row_factory = sqlite3.Row
    conns[kind] = (version, conn)
    return conn


def release_site_dbs():
    for _, conn in getattr(_site_conns, 'conns', {}).values():
        conn.close()
    _site_conns.conns = {}


# Altitude-regime buckets for the ADD OBJ search form, keyed on mean
# altitude ((perigee+apogee)/2). Same cutoffs as server.js: LEO below
# 2,000km, GEO within +/-200km of the 35,786km geostationary altitude, MEO
# the gap between, OTHER (HEO/Molniya/GTO/beyond) above GEO.
ALTITUDE_REGIME_SQL = {
    'LEO': '(o.perigee + o.apogee) / 2.0 < 2000',
    'MEO': '(o.perigee + o.apogee) / 2.0 >= 2000 AND (o.perigee + o.apogee) / 2.0 < 35586',
    'GEO': '(o.perigee + o.apogee) / 2.0 >= 35586 AND (o.perigee + o.apogee) / 2.0 <= 35986',
    'OTHER': '(o.perigee + o.apogee) / 2.0 > 35986',
}

# Inclination bands for the same form -- covers the full 0-180 degree range.
INCLINATION_BAND_RANGES = {
    'EQUATORIAL': (0, 20),
    'MID': (20, 80),
    'POLAR_SSO': (80, 180),
}

RESULT_SCAN_LIMIT = 4000
RESULT_LIMIT = 500


def get_param(query_params, name):
    """Matches URLSearchParams.get() -- first value, or None if absent."""
    values = query_params.get(name)
    return values[0] if values else None


def get_float_param(query_params, name):
    """Same as get_param(), but parsed to float -- an unparseable value is
    treated as absent (no filter applied) rather than a 500, matching this
    endpoint's general tolerance for malformed query input elsewhere."""
    value = get_param(query_params, name)
    try:
        return float(value) if value else None
    except ValueError:
        return None


def json_response(start_response, status, payload):
    body = json.dumps(payload).encode('utf-8')
    start_response(status, [('Content-Type', 'application/json'), ('Content-Length', str(len(body)))])
    return [body]


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def handle_news(query_params, start_response):
    try:
        limit_param = get_param(query_params, 'limit')
        try:
            limit = int(limit_param)
        except (TypeError, ValueError):
            limit = 50

        # Optional, repeatable: ?topic=launch&topic=eo returns articles
        # tagged with ANY of the given topics (see scripts/topicRules.py).
        # Unknown topics simply match nothing.
        topics = [topic for topic in query_params.get('topic', []) if topic]
        where_clause = ''
        params = []
        if topics:
            placeholders = ','.join('?' * len(topics))
            where_clause = f'WHERE id IN (SELECT articleID FROM articleTopics WHERE topic IN ({placeholders}))'
            params = topics

        # MODIFIED: Added 'url' to the SELECT statement (kept in sync with server.js)
        try:
            rows = site_db('news').execute(
                f'SELECT title, source, published_date, url, description FROM articles {where_clause} '
                'ORDER BY published_date DESC LIMIT ?',
                params + [limit],
            ).fetchall()
        except sqlite3.OperationalError as e:
            # A database not yet tagged (no tagNews.py / readNews.py run since
            # this was deployed) has no articleTopics table -- nothing is
            # tagged yet, so a topic filter matches nothing.
            if topics and 'no such table' in str(e):
                rows = []
            else:
                raise
        return json_response(start_response, '200 OK', rows_to_dicts(rows))
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# Rows of the landing page's data-freshness table, in display order.
# `jobs` are the names ingestion scripts record in ingestionRuns
# (scripts/ingestionLog.py) -- the newest of any of them counts; the
# pre-refactor names stay listed until the live server is migrated
# (0_documentation/plans/dbRefactorPlan.md, step 12). The site files carry every source's runs
# (publishSite.py), plus the publish itself (publishOrbital, the time the
# EIRP figures were computed). `interval_min` must match
# that job's cron schedule (setupCron.sh / scripts/runPipeline.sh) -- the
# next sync is estimated as the last run's start plus this interval, which
# stays right whatever timezone the host's cron uses. `fallback_sql` gives a
# last-refresh time for a database with no recorded runs yet.
STATUS_SOURCES = [
    {'data': 'News', 'source': '18 RSS feeds', 'db': 'news', 'jobs': ('news',), 'interval_min': 30,
     'fallback_sql': 'SELECT MAX(fetched_at) FROM articles'},
    # NORAD = the US satellite catalogue; Space-Track publishes it.
    {'data': 'Orbital elements', 'source': 'NORAD via Space-Track', 'db': 'orbital',
     'jobs': ('spaceTrackRecent', 'spaceTrackFull', 'orbitalElements'), 'interval_min': 12 * 60,
     'fallback_sql': 'SELECT MAX(fetchedAt) FROM orbital_objects'},
    {'data': 'Satellite catalogue', 'source': 'NORAD SATCAT via Space-Track', 'db': 'orbital',
     'jobs': ('spaceTrackFull', 'satcat'), 'interval_min': 24 * 60},
    {'data': 'Satellite groups', 'source': 'CelesTrak · our own rules', 'db': 'orbital',
     'jobs': ('celesTrakGroups',), 'interval_min': 7 * 24 * 60},
    {'data': 'Downlink EIRP', 'source': 'Filings · band plans', 'db': 'orbital', 'jobs': ('publishOrbital', 'eirp'),
     'interval_min': 12 * 60},
    {'data': 'Radio frequencies', 'source': 'SatNOGS DB', 'db': 'orbital', 'jobs': ('satnogs', 'satnogsRf'),
     'interval_min': 12 * 60},
    {'data': 'Launch & ownership', 'source': 'GCAT', 'db': 'gcat', 'jobs': ('gcat',),
     'interval_min': 7 * 24 * 60},
    # Space weather (siteWeather.db, scripts/publishSite.py). Intervals match setupCron.sh.
    {'data': 'Space weather', 'source': 'NOAA SWPC', 'db': 'weather', 'jobs': ('swpcFast',), 'interval_min': 15},
    {'data': 'Solar wind & X-ray (L1, GOES)', 'source': 'NOAA SWPC', 'db': 'weather', 'jobs': ('swpcSlow',),
     'interval_min': 60},
    {'data': 'Geomagnetic indices', 'source': 'GFZ Potsdam', 'db': 'weather', 'jobs': ('gfz',), 'interval_min': 60},
    {'data': 'Solar events', 'source': 'NASA DONKI', 'db': 'weather', 'jobs': ('donki',), 'interval_min': 60},
    {'data': 'Cosmic rays (neutron monitors)', 'source': 'Oulu cosmic ray station', 'db': 'weather', 'jobs': ('gcr',),
     'interval_min': 60},
    {'data': 'Cosmic rays, monthly record', 'source': 'Oulu cosmic ray station', 'db': 'weather',
     'jobs': ('gcrMonthly',), 'interval_min': 31 * 24 * 60},
    {'data': 'Sunspot number (monthly)', 'source': 'WDC-SILSO', 'db': 'weather', 'jobs': ('silso',),
     'interval_min': 31 * 24 * 60},
    {'data': 'Ionosphere maps (CODE)', 'source': 'CODE, University of Bern', 'db': 'weather', 'jobs': ('tecCode',),
     'interval_min': 24 * 60},
    {'data': 'Ionosphere maps (GloTEC)', 'source': 'NOAA SWPC', 'db': 'weather', 'jobs': ('tecGlotec',),
     'interval_min': 3 * 60},
]


def gcat_db():
    """The GCAT tables (siteOrbital.db, or GCAT attached to the legacy
    orbital connection) -- or None while no orbital database exists."""
    return site_db('orbital')


def stats_db():
    """The ON-ORBIT figures (siteOrbital.db, or onOrbitStats.db attached to
    the legacy orbital connection) -- or None while none exists."""
    return site_db('orbital')


def to_utc_iso(value):
    """SQLite CURRENT_TIMESTAMP text ('YYYY-MM-DD HH:MM:SS', UTC) or an ISO
    string -> 'YYYY-MM-DDTHH:MM:SSZ'; None stays None."""
    if not value:
        return None
    text = str(value).replace(' ', 'T')
    return text if text.endswith('Z') else text[:19] + 'Z'


def add_minutes_iso(iso_value, minutes):
    parsed = datetime.strptime(iso_value[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    return (parsed + timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')


def latest_runs(conn, jobs, table='ingestionRuns'):
    """(latest run, latest successful run) of any of `jobs`, each a
    sqlite3.Row or None -- (None, None) for a database with no runs table
    yet. A site file's table holds every source's runs (publishSite.py);
    ordered by finish time, as it has no id column."""
    marks = ','.join('?' * len(jobs))
    try:
        latest = conn.execute(
            f'SELECT startedAt, finishedAt, succeeded, changes FROM {table} '
            f'WHERE job IN ({marks}) ORDER BY finishedAt DESC LIMIT 1', jobs).fetchone()
        latest_ok = conn.execute(
            f'SELECT startedAt, finishedAt, succeeded, changes FROM {table} '
            f'WHERE job IN ({marks}) AND succeeded = 1 ORDER BY finishedAt DESC LIMIT 1', jobs).fetchone()
    except sqlite3.OperationalError as e:
        if 'no such table' in str(e):
            return None, None
        raise
    return latest, latest_ok


def status_row(spec):
    row = {'data': spec['data'], 'source': spec['source'], 'lastRefreshUtc': None,
           'changes': None, 'lastRunFailed': False, 'nextSyncUtc': None}

    conn = site_db(spec['db'] if spec['db'] in ('news', 'weather') else 'orbital')
    if conn is None:
        return row   # database not created yet -- nothing recorded
    # Before the live server's migration, GCAT's runs are in its own file,
    # attached to the legacy orbital connection as legacy1.
    _, legacy = site_files('orbital')
    table = 'legacy1.ingestionRuns' if legacy and spec['db'] == 'gcat' else 'ingestionRuns'
    latest, latest_ok = latest_runs(conn, spec['jobs'], table)
    if latest is not None:
        row['lastRunFailed'] = not latest['succeeded']
        row['nextSyncUtc'] = add_minutes_iso(latest['startedAt'], spec['interval_min'])
        if latest_ok is not None:
            row['lastRefreshUtc'] = to_utc_iso(latest_ok['finishedAt'])
            row['changes'] = latest_ok['changes']
    elif spec.get('fallback_sql'):
        row['lastRefreshUtc'] = to_utc_iso(conn.execute(spec['fallback_sql']).fetchone()[0])
        if row['lastRefreshUtc']:
            row['nextSyncUtc'] = add_minutes_iso(row['lastRefreshUtc'], spec['interval_min'])
    return row


# WEATHER > SUN NOW: when each live solar image was made. The pictures go
# from the visitor's browser straight to NASA and NOAA, but NASA doesn't let
# a page read an image's timestamp, so the server asks each source for the
# headers only (a HEAD request: a few hundred bytes, no picture), at most
# once per SUN_TIMES_KEEP_SEC (30 minutes) however many visitors there are, with a short
# random pause between requests, and serves the answer from memory in
# between. The addresses are fixed here, never taken from the request.
SUN_IMAGE_URLS = {
    'hmiIntensity': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMIIC.jpg',
    'hmiMagnetogram': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMIB.jpg',
    'aia193': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg',
    'aia131': 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0131.jpg',
    'lascoC2': 'https://services.swpc.noaa.gov/images/animations/lasco-c2/latest.jpg',
    'lascoC3': 'https://services.swpc.noaa.gov/images/animations/lasco-c3/latest.jpg',
}
SUN_TIMES_KEEP_SEC = 30 * 60
SUN_TIMES_TIMEOUT_SEC = 5
SUN_TIMES_USER_AGENT = 'LCARS-FAS/1.0 (+https://gaps2024.com/LCARS-FAS)'
MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
sun_times_cache = {'at': 0.0, 'times': None}
sun_times_lock = threading.Lock()


def format_dtg(http_date):
    """'Sat, 24 Oct 2026 12:40:14 GMT' -> '241240Z OCT 26' (UTC), or None."""
    try:
        when = parsedate_to_datetime(http_date).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
    return f'{when:%d%H%M}Z {MONTHS[when.month - 1]} {when:%y}'


def fetch_sun_times():
    times = {}
    for index, (key, url) in enumerate(SUN_IMAGE_URLS.items()):
        if index:
            time.sleep(random.uniform(0.3, 0.8))
        request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': SUN_TIMES_USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=SUN_TIMES_TIMEOUT_SEC) as response:
                times[key] = format_dtg(response.headers.get('Last-Modified'))
        except (urllib.error.URLError, OSError, ValueError):
            times[key] = None
    return times


def sun_times():
    with sun_times_lock:
        if sun_times_cache['times'] is None or time.time() - sun_times_cache['at'] > SUN_TIMES_KEEP_SEC:
            sun_times_cache['times'] = fetch_sun_times()
            sun_times_cache['at'] = time.time()
        return sun_times_cache['times']


def handle_sun_times(start_response):
    try:
        return json_response(start_response, '200 OK', {'times': sun_times()})
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# WEATHER panels: the data in siteWeather.db (scripts/publishSite.py), as
# compact arrays. Gzipped, with an ETag and browser-cached like the sky data
# (cached_json_response()); one cache entry per query, rebuilt when the file
# is swapped (every changing ingestion run, so at most every 15 minutes).
WEATHER_MAX_AGE_SEC = 5 * 60
WEATHER_RANGES = {'6h': 0.25, '24h': 1, '3d': 3, '7d': 7, '30d': 30, '90d': 90, '400d': 400,   # 400d: 13 months of daily F10.7
                  '25y': 9200,                                                                # the solar-cycle chart (monthly sunspot number)
                  'all': 120000}                                                              # the monthly records (since 1749)
WEATHER_NATIVE_MAX_DAYS = 3   # up to here the native samples; beyond, hourly means (publishSite.WEATHER_NATIVE_DAYS)
WEATHER_NAME = re.compile(r'^[A-Za-z0-9]{1,64}$')
WEATHER_EVENT_LIMIT = 500
_weather_caches = {}


def weather_cache(key):
    if len(_weather_caches) > 64 and key not in _weather_caches:
        _weather_caches.clear()   # the keys are validated, so this stays small; clear rather than grow
    return _weather_caches.setdefault(key, {})


def weather_cutoff(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')


def weather_now_payload():
    """Newest non-missing reading of each series that is not in the future:
    {series: [tsUtc, value, unit, quality]}, and the names of the maps held."""
    db = site_db('weather')
    now = weather_cutoff(0)
    rows = db.execute(
        'SELECT s.series, s.tsUtc, s.value, s.unit, s.quality FROM samples s JOIN ('
        'SELECT series, MAX(tsUtc) AS t FROM samples WHERE value IS NOT NULL AND tsUtc <= ? GROUP BY series) m '
        'ON m.series = s.series AND m.t = s.tsUtc', (now,)).fetchall()
    return {'generatedUtc': now,
            'latest': {r['series']: [r['tsUtc'], r['value'], r['unit'], r['quality']] for r in rows},
            'maps': [r[0] for r in db.execute('SELECT name FROM latestMaps ORDER BY name')]}


def handle_weather_now(environ, start_response):
    return cached_json_response(environ, start_response, weather_cache('now'), weather_now_payload, 'weather',
                                WEATHER_MAX_AGE_SEC, 'Weather data unavailable ({})')


def weather_series_payload(name, rng, quality=False, sig=None):
    """{t, v} for a series; with quality=True also q, the quality text of each sample (burst?, provisional, forecast
    included ...), for the charts that draw such samples differently. sig: round the values to that many significant
    figures (a log-scale chart cannot show more, and 4 figures instead of 16 makes the answer a third of the size)."""
    db = site_db('weather')
    days = WEATHER_RANGES[rng]
    table = 'samples'
    if days > WEATHER_NATIVE_MAX_DAYS and db.execute(
            'SELECT 1 FROM samplesHourly WHERE series = ? LIMIT 1', (name,)).fetchone():
        table = 'samplesHourly'
    qualityColumn = 'quality' if table == 'samples' else 'NULL'   # hourly means carry a reading count, not a quality
    rows = db.execute(f'SELECT tsUtc, value, unit, {qualityColumn} AS quality FROM {table} WHERE series = ? AND tsUtc >= ? ORDER BY tsUtc',
                      (name, weather_cutoff(days))).fetchall()
    values = [r['value'] for r in rows]
    if sig:
        values = [v if v is None or v == 0 else float(f'{v:.{sig - 1}e}') for v in values]
    payload = {'name': name, 'range': rng, 'resolution': 'hourly' if table == 'samplesHourly' else 'native',
               'unit': rows[0]['unit'] if rows else None, 't': [r['tsUtc'] for r in rows], 'v': values}
    if quality:
        payload['q'] = [r['quality'] for r in rows]
    return payload


def handle_weather_series(environ, query_params, start_response):
    name, rng = get_param(query_params, 'name') or '', get_param(query_params, 'range') or '24h'
    quality = get_param(query_params, 'quality') == '1'
    try:
        sig = min(max(int(get_param(query_params, 'sig') or 0), 0), 12) or None
    except ValueError:
        sig = None
    if not WEATHER_NAME.match(name) or rng not in WEATHER_RANGES:
        return json_response(start_response, '400 Bad Request',
                             {'error': 'need name and a range of ' + ', '.join(WEATHER_RANGES)})
    db = site_db('weather')
    if db is None:
        return json_response(start_response, '503 Service Unavailable', {'error': 'Weather data unavailable'})
    if not db.execute('SELECT 1 FROM samples WHERE series = ? LIMIT 1', (name,)).fetchone():
        return json_response(start_response, '404 Not Found', {'error': 'no such series'})
    return cached_json_response(environ, start_response, weather_cache(('series', name, rng, quality, sig)),
                                lambda: weather_series_payload(name, rng, quality, sig), 'weather', WEATHER_MAX_AGE_SEC,
                                'Weather data unavailable ({})')


def weather_events_payload(eventType, days):
    rows = site_db('weather').execute(
        'SELECT eventType, startUtc, eventID, json FROM events WHERE eventType = ? AND startUtc >= ? '
        'ORDER BY startUtc DESC LIMIT ?', (eventType, weather_cutoff(days), WEATHER_EVENT_LIMIT)).fetchall()
    return {'type': eventType, 'days': days,
            'events': [{'startUtc': r['startUtc'], 'id': r['eventID'], 'record': json.loads(r['json'])} for r in rows]}


def handle_weather_events(environ, query_params, start_response):
    eventType = get_param(query_params, 'type') or ''
    try:
        days = min(max(int(get_param(query_params, 'days') or 30), 1), 365)
    except ValueError:
        days = 30
    if not WEATHER_NAME.match(eventType):
        return json_response(start_response, '400 Bad Request', {'error': 'need type'})
    return cached_json_response(environ, start_response, weather_cache(('events', eventType, days)),
                                lambda: weather_events_payload(eventType, days), 'weather', WEATHER_MAX_AGE_SEC,
                                'Weather data unavailable ({})')


def weather_map_payload(name):
    row = site_db('weather').execute('SELECT tsUtc, json FROM latestMaps WHERE name = ?', (name,)).fetchone()
    return {'name': name, 'tsUtc': row['tsUtc'], 'map': json.loads(row['json'])}


def handle_weather_map(environ, query_params, start_response):
    name = get_param(query_params, 'name') or ''
    if not WEATHER_NAME.match(name):
        return json_response(start_response, '400 Bad Request', {'error': 'need name'})
    db = site_db('weather')
    if db is None:
        return json_response(start_response, '503 Service Unavailable', {'error': 'Weather data unavailable'})
    if not db.execute('SELECT 1 FROM latestMaps WHERE name = ?', (name,)).fetchone():
        return json_response(start_response, '404 Not Found', {'error': 'no such map'})
    return cached_json_response(environ, start_response, weather_cache(('map', name)),
                                lambda: weather_map_payload(name), 'weather', WEATHER_MAX_AGE_SEC,
                                'Weather data unavailable ({})')


# WEATHER values at any place: a lookup in the stored global maps (OVATION
# aurora index, 1 degree grid; D-RAP absorption, 4 x 2 degree grid), nearest
# cell. No place is special: the panel sends the latitude and longitude it wants.
# The parsed maps are kept in memory until the weather file is swapped.
_aurora_cache = {}


def weather_maps():
    """(ovation, drap) records, each None if not held."""
    key = site_version('weather')
    if _aurora_cache.get('key') != key:
        db = site_db('weather')
        found = {}
        for name in ('ovation', 'drapGlobal'):
            row = db.execute('SELECT json FROM latestMaps WHERE name = ?', (name,)).fetchone()
            found[name] = json.loads(row['json']) if row else None
        _aurora_cache.update(key=key, ovation=found['ovation'], drap=found['drapGlobal'])
    return _aurora_cache['ovation'], _aurora_cache['drap']


def weather_float(query_params, name, low, high):
    """The parameter as a finite float within [low, high], else None."""
    try:
        value = float(get_param(query_params, name))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def aurora_at(ovation, drap, lat, lon):
    lon = lon % 360   # -180..360 all mean a longitude
    row = min(180, max(0, int(round(lat - ovation['latMin']))))
    col = int(round(lon)) % 360
    result = {'lat': lat, 'lon': lon if lon <= 180 else lon - 360,
              'aurora': {'index': ovation['rows'][row][col], 'cellLat': row + ovation['latMin'],
                         'cellLon': col if col < 180 else col - 360,
                         'observedUtc': ovation['obs'], 'forecastUtc': ovation['forecast']}}
    if drap:
        r = min(len(drap['tenths']) - 1, max(0, int(round((lat - drap['latMax']) / drap['latStep']))))
        c = int(round((((lon + 180) % 360 - 180) - drap['lonMin']) / drap['lonStep'])) % len(drap['tenths'][0])
        result['absorption'] = {'mhz': drap['tenths'][r][c] / 10, 'validUtc': drap['valid']}
    return result


def handle_weather_aurora_at(query_params, start_response):
    lat = weather_float(query_params, 'lat', -90, 90)
    lon = weather_float(query_params, 'lon', -180, 360)
    if lat is None or lon is None:
        return json_response(start_response, '400 Bad Request', {'error': 'need lat (-90 to 90) and lon (-180 to 360)'})
    try:
        ovation, drap = weather_maps()
    except (OSError, sqlite3.Error):
        return json_response(start_response, '503 Service Unavailable', {'error': 'Weather data unavailable'})
    if ovation is None:
        return json_response(start_response, '404 Not Found', {'error': 'no aurora map held yet'})
    return json_response(start_response, '200 OK', aurora_at(ovation, drap, lat, lon))


# WEATHER > TEC (total electron content) maps, from tecMaps in siteWeather.db (scripts/ingestionTEC.py):
# CODE (Bern), hourly maps observed and predicted, 71 x 73 cells of 2.5 x 5 degrees; and NOAA GloTEC, every
# 3 hours, 72 x 72 cells of 2.5 x 5 degrees with TEC, anomaly, NmF2 and hmF2. Each map is stored as gzipped
# compact JSON and handed out as it is (a few kB for CODE, about 20 kB for GloTEC). Seven days are held.
#   tec-index   what is held (cached with the weather file)
#   tec-code    one CODE map: kind (observed|prediction), day (yyyy-mm-dd), hour (0-23), optional product
#   tec-latest  the newest GloTEC map, refreshed from NOAA on demand (see tec_refresh); its q list is the quality flag;
#               optional fields=tec,anom,q (any of tec, anom, nmf2, hmf2, q) sends only those lists (the map view needs three of the five)
#               (0 = no observations: grey the anomaly out; see the ingestionTEC.py docstring)
#   tec-at      TEC (both sources), and foF2 from GloTEC, at a latitude and longitude: nearest cell
#   tec-series  the same over the stored 7 days
#   tec-summary the newest STORED GloTEC map in a few numbers (never asks NOAA): the largest TEC where it is observed, and
#               the third-largest anomaly as a fraction of the cell's own median, among well-observed cells; the lamp of the HF COMMS board
TEC_KINDS = ('observed', 'prediction')
TEC_PRODUCTS = ('rapid', 'pred1', 'pred2', 'pred5')
TEC_KEEP_SEC = 30 * 60      # NOAA is asked at most this often, however many visitors there are
TEC_RETRY_SEC = 2 * 60      # after a failed fetch, the held map is served for this long before NOAA is asked again
TEC_FOF2_PER_SQRT_NMF2 = 0.898   # foF2 (MHz) = 8.98 sqrt(NmF2 / 1e12 m-3); GloTEC's nmf2 is in 1e10 m-3
_tec_latest = {'checkedAt': 0.0, 'failedAt': 0.0, 'validUtc': None, 'gz': None}
_tec_lock = threading.Lock()
tec_fetch = None            # tests put a stand-in here; None means the real, paced fetcher


def stored_gzip_response(environ, start_response, blob, tag, max_age, extra=()):
    """Serves a body that is held gzipped (a TEC map): as it is to a browser that accepts gzip, unpacked
    for one that does not; ETag from `tag`, 304 for a matching If-None-Match."""
    use_gzip = 'gzip' in environ.get('HTTP_ACCEPT_ENCODING', '')
    etag = '"' + re.sub(r'[^A-Za-z0-9]', '', tag) + ('-gz' if use_gzip else '') + '"'
    headers = [('Content-Type', 'application/json'), ('Vary', 'Accept-Encoding'), ('ETag', etag),
               ('Cache-Control', f'max-age={max_age}, must-revalidate'), *extra]
    if etag in [t.strip() for t in environ.get('HTTP_IF_NONE_MATCH', '').split(',')]:
        start_response('304 Not Modified', headers)
        return [b'']
    body = bytes(blob) if use_gzip else gzip.decompress(bytes(blob))
    if use_gzip:
        headers.append(('Content-Encoding', 'gzip'))
    headers.append(('Content-Length', str(len(body))))
    start_response('200 OK', headers)
    return [body]


def tec_unpack(blob):
    return json.loads(gzip.decompress(bytes(blob)).decode('utf-8'))


def tec_published_glotec():
    """(validUtc, gz) of the newest GloTEC map in the published file, or None."""
    db = site_db('weather')
    row = db.execute("SELECT validUtc, gz FROM tecMaps WHERE source = 'glotec' ORDER BY validUtc DESC LIMIT 1").fetchone() if db else None
    return (row['validUtc'], bytes(row['gz'])) if row else None


def tec_newest_glotec():
    """(validUtc, gz) of the newest GloTEC map: the published one or, if newer, the one this server fetched. None if neither."""
    try:
        held = tec_published_glotec()
    except sqlite3.Error:
        held = None
    mine = (_tec_latest['validUtc'], _tec_latest['gz']) if _tec_latest['gz'] else None
    return max((x for x in (held, mine) if x), default=None)


def tec_refresh():
    """-> (newest GloTEC map as (validUtc, gz) or None, stale). NOAA is asked at most once every TEC_KEEP_SEC
    (its directory listing, then a map only if one newer than the one held is listed), and by ONE request at a
    time: a second request waits for the lock and then finds the answer. After a failure the held map is
    served (stale) and NOAA is left alone for TEC_RETRY_SEC. The fetched map is kept in memory only: visitors
    never write to the databases; the 3-hourly cron job is what stores the history."""
    import ingestionTEC
    with _tec_lock:
        now, best = time.time(), tec_newest_glotec()
        if best and now - _tec_latest['checkedAt'] < TEC_KEEP_SEC:
            return best, False
        if now - _tec_latest['failedAt'] < TEC_RETRY_SEC:
            return best, True
        try:
            found = ingestionTEC.fetchLatestGlotec(tec_fetch or ingestionTEC.Fetcher(),
                                                   datetime.now(timezone.utc).replace(tzinfo=None),
                                                   lambda valid: best is not None and valid <= best[0])
            if found:
                record = found[0]
                _tec_latest.update(validUtc=record['validUtc'], gz=ingestionTEC.packMap(record))
                best = (record['validUtc'], _tec_latest['gz'])
            _tec_latest['checkedAt'] = now
            return best, False
        except Exception:
            _tec_latest['failedAt'] = now
            return best, True


TEC_GLOTEC_FIELDS = ('tec', 'anom', 'nmf2', 'hmf2', 'q')   # the five flat lists of a GloTEC record
_tec_fields_cache = {}


def tec_trimmed(validUtc, gz, fields):
    """The GloTEC record with only the lists named in `fields` (a tuple) among its five (the other keys stay), gzipped; kept per
    map and field set, so the map view's three lists (about 35% smaller than all five) are packed once, not per visitor."""
    key = (validUtc, fields)
    if key not in _tec_fields_cache:
        if len(_tec_fields_cache) > 8:
            _tec_fields_cache.clear()
        record = {k: v for k, v in tec_unpack(gz).items() if k not in TEC_GLOTEC_FIELDS or k in fields}
        _tec_fields_cache[key] = gzip.compress(json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8'), 9)
    return _tec_fields_cache[key]


def handle_weather_tec_latest(environ, query_params, start_response):
    wanted = get_param(query_params, 'fields')
    fields = tuple(sorted(set(wanted.split(',')))) if wanted else None
    if fields is not None and not set(fields) <= set(TEC_GLOTEC_FIELDS):
        return json_response(start_response, '400 Bad Request', {'error': 'fields: any of ' + ', '.join(TEC_GLOTEC_FIELDS) + ', comma-separated'})
    best, stale = tec_refresh()
    if best is None:
        return json_response(start_response, '503 Service Unavailable', {'error': 'GloTEC unavailable'})
    blob, tag = (best[1], 'glotec' + best[0]) if fields is None else (tec_trimmed(best[0], best[1], fields), 'glotec' + best[0] + ''.join(fields))
    return stored_gzip_response(environ, start_response, blob, tag, 60 if stale else WEATHER_MAX_AGE_SEC,
                                [('X-Tec-Stale', '1')] if stale else [])


def handle_weather_tec_code(environ, query_params, start_response):
    kind, product = get_param(query_params, 'kind'), get_param(query_params, 'product')
    day, hour = get_param(query_params, 'day') or '', get_param(query_params, 'hour') or ''
    try:
        datetime.strptime(day, '%Y-%m-%d')
        hour = int(hour)
    except ValueError:
        hour = None
    if kind not in TEC_KINDS or hour is None or not 0 <= hour <= 23 or (product is not None and product not in TEC_PRODUCTS):
        return json_response(start_response, '400 Bad Request', {
            'error': 'need kind (observed or prediction), day (yyyy-mm-dd), hour (0 to 23) and optionally product (' + ', '.join(TEC_PRODUCTS) + ')'})
    valid = f'{day}T{hour:02d}:00:00Z'
    try:
        db = site_db('weather')
        if db is None:
            raise FileNotFoundError('no weather database')
        row = db.execute("SELECT product, issuedUtc, gz FROM tecMaps WHERE source = 'code' AND kind = ? AND validUtc = ? "
                         "AND (? IS NULL OR product = ?) ORDER BY issuedUtc DESC LIMIT 1", (kind, valid, product, product)).fetchone()
    except (OSError, sqlite3.Error):
        return json_response(start_response, '503 Service Unavailable', {'error': 'Weather data unavailable'})
    if row is None:
        return json_response(start_response, '404 Not Found', {'error': 'no such map held'})
    return stored_gzip_response(environ, start_response, row['gz'], f'{row["product"]}{row["issuedUtc"]}{valid}', WEATHER_MAX_AGE_SEC)


def tec_index_payload():
    """What is held. code: {kind: {day: {hour: [product, issuedUtc]}}} (the newest issue of each hour); glotec: the valid times."""
    code, glotec = {kind: {} for kind in TEC_KINDS}, []
    for r in site_db('weather').execute('SELECT source, product, kind, issuedUtc, validUtc FROM tecMaps ORDER BY validUtc, issuedUtc'):
        if r['source'] == 'glotec':
            glotec.append(r['validUtc'])
        else:
            code[r['kind']].setdefault(r['validUtc'][:10], {})[str(int(r['validUtc'][11:13]))] = [r['product'], r['issuedUtc']]
    return {'code': code, 'glotec': sorted(set(glotec))}


def handle_weather_tec_index(environ, start_response):
    return cached_json_response(environ, start_response, weather_cache('tecIndex'), tec_index_payload, 'weather',
                                WEATHER_MAX_AGE_SEC, 'Weather data unavailable ({})')


def tec_cell(record, lat, lon):
    """(row, column) of the cell nearest a place in a CODE or GloTEC record, and that cell's latitude and longitude."""
    lon = (lon + 180) % 360 - 180
    if record['source'] == 'code':
        row = min(70, max(0, int(round((lat - record['latMax']) / record['latStep']))))
        col = min(72, max(0, int(round((lon - record['lonMin']) / record['lonStep']))))
        return row, col, record['latMax'] + row * record['latStep'], record['lonMin'] + col * record['lonStep']
    row = min(record['nLat'] - 1, max(0, int(round((lat - record['latMin']) / record['latStep']))))
    col = int(round((lon - record['lonMin']) / record['lonStep'])) % record['nLon']
    return row, col, record['latMin'] + row * record['latStep'], record['lonMin'] + col * record['lonStep']


def tec_glotec_point(record, row, col):
    """The values of one GloTEC cell in plain units; foF2 from NmF2 is indicative only."""
    i = row * record['nLon'] + col
    tenths = lambda v: None if v is None else v / 10   # noqa: E731
    nmf2 = record['nmf2'][i]
    flag = record['q'][i]
    return {'tec': tenths(record['tec'][i]), 'anomaly': tenths(record['anom'][i]), 'nmF2': nmf2,
            'observed': bool(flag), 'anomalyReliable': bool(flag),     # flag 0: no observations, the value is the model's estimate; nmF2 in 1e10 m-3
            'hmF2': record['hmf2'][i], 'foF2': None if nmf2 is None else round(TEC_FOF2_PER_SQRT_NMF2 * math.sqrt(nmf2), 2),
            'quality': record['q'][i]}


def handle_weather_tec_at(query_params, start_response):
    lat = weather_float(query_params, 'lat', -90, 90)
    lon = weather_float(query_params, 'lon', -180, 360)
    if lat is None or lon is None:
        return json_response(start_response, '400 Bad Request', {'error': 'need lat (-90 to 90) and lon (-180 to 360)'})
    result = {'lat': lat, 'lon': (lon + 180) % 360 - 180, 'glotec': None, 'code': None, 'foF2Note': 'indicative: 8.98 sqrt(NmF2)',
              'anomalyUnit': 'TECU (inferred)', 'anomalyNote': 'deviation from the 30-day median; where observed is false there are no '
              'observations and the anomaly is the seasonal and F10.7 response of the model, not observed weather',
              'qualityMeaning': 'mean number of F-region observations per profile, 0 (none, model estimate) to 5 (dense); coverage, not error'}
    held = None
    try:
        best = tec_newest_glotec()
        if best:
            record = tec_unpack(best[1])
            row, col, cellLat, cellLon = tec_cell(record, lat, lon)
            result['glotec'] = {'validUtc': record['validUtc'], 'cellLat': cellLat, 'cellLon': cellLon, **tec_glotec_point(record, row, col)}
        db = site_db('weather')
        if db is None:
            raise FileNotFoundError('no weather database')
        hour = datetime.now(timezone.utc) + timedelta(minutes=30)     # the nearest hourly map
        valid = hour.strftime('%Y-%m-%dT%H:00:00Z')
        held = db.execute("SELECT product, kind, issuedUtc, gz FROM tecMaps WHERE source = 'code' AND validUtc = ? "
                          "ORDER BY kind = 'observed' DESC, issuedUtc DESC LIMIT 1", (valid,)).fetchone()
    except (OSError, sqlite3.Error):
        if result['glotec'] is None:
            return json_response(start_response, '503 Service Unavailable', {'error': 'Weather data unavailable'})
    if held:
        record = tec_unpack(held['gz'])
        row, col, cellLat, cellLon = tec_cell(record, lat, lon)
        value = record['rows'][row][col]
        result['code'] = {'validUtc': record['validUtc'], 'issuedUtc': record['issuedUtc'], 'kind': record['kind'],
                          'product': record['product'], 'cellLat': cellLat, 'cellLon': cellLon,
                          'tec': None if value is None else value / 10}
    if result['glotec'] is None and result['code'] is None:
        return json_response(start_response, '404 Not Found', {'error': 'no TEC map held yet'})
    return json_response(start_response, '200 OK', result)


def tec_series_payload(lat, lon):
    """For the cells nearest the place: TEC (and, from GloTEC, anomaly and foF2) in the nearest cell of every stored map: GloTEC; CODE observed
    (the newest issue of each hour) and CODE predicted (the newest issue of each hour after the last observed one)."""
    db = site_db('weather')
    glotec = {'t': [], 'tec': [], 'anomaly': [], 'foF2': [], 'observed': []}
    cell = None
    for r in db.execute("SELECT validUtc, gz FROM tecMaps WHERE source = 'glotec' ORDER BY validUtc"):
        record = tec_unpack(r['gz'])
        row, col, cellLat, cellLon = tec_cell(record, lat, lon)
        point = tec_glotec_point(record, row, col)
        cell = {'cellLat': cellLat, 'cellLon': cellLon}
        glotec['t'].append(r['validUtc'])
        for key in ('tec', 'anomaly', 'foF2', 'observed'):
            glotec[key].append(point[key])
    code = {'observed': {'t': [], 'tec': []}, 'prediction': {'t': [], 'tec': [], 'product': []}}
    codeCell = None
    newest = {}
    for r in db.execute("SELECT kind, validUtc, product, gz FROM tecMaps WHERE source = 'code' ORDER BY validUtc, issuedUtc"):
        newest[(r['kind'], r['validUtc'])] = r         # a later issue replaces an earlier one
    lastObserved = max((v for k, v in newest if k == 'observed'), default='')
    for (kind, valid), r in sorted(newest.items(), key=lambda item: (item[0][1], item[0][0])):
        if kind == 'prediction' and valid <= lastObserved:
            continue
        record = tec_unpack(r['gz'])
        row, col, cellLat, cellLon = tec_cell(record, lat, lon)
        codeCell = {'cellLat': cellLat, 'cellLon': cellLon}
        value = record['rows'][row][col]
        code[kind]['t'].append(valid)
        code[kind]['tec'].append(None if value is None else value / 10)
        if kind == 'prediction':
            code[kind]['product'].append(r['product'])
    return {'glotec': {**(cell or {}), **glotec}, 'code': {**(codeCell or {}), **code},
            'foF2Note': 'indicative: 8.98 sqrt(NmF2) from GloTEC, MHz', 'anomalyUnit': 'TECU (inferred)',
            'anomalyNote': 'grey the anomaly where observed is false (no observations: the model response, not weather)'}


def handle_weather_tec_series(environ, query_params, start_response):
    lat = weather_float(query_params, 'lat', -90, 90)
    lon = weather_float(query_params, 'lon', -180, 360)
    if lat is None or lon is None:
        return json_response(start_response, '400 Bad Request', {'error': 'need lat (-90 to 90) and lon (-180 to 360)'})
    # one cache entry per pair of cells (GloTEC's and CODE's), not per query
    east = (lon + 180) % 360 - 180
    key = ('tecSeries', round((lat + 88.75) / 2.5), round((east + 177.5) / 5) % 72, round((87.5 - lat) / 2.5), round((east + 180) / 5))
    return cached_json_response(environ, start_response, weather_cache(key), lambda: tec_series_payload(lat, lon), 'weather',
                                WEATHER_MAX_AGE_SEC, 'Weather data unavailable ({})')


TEC_SUMMARY_MIN_FLAG = 3       # cells with at least this quality flag count as well observed (see ingestionTEC.py)
TEC_SUMMARY_MIN_MEDIAN = 10.0  # TECU: the fraction anomaly / median means little where the median is tiny
_tec_summary_cache = {}


def tec_summary_of(record):
    """Numbers from one GloTEC record for the HF COMMS GNSS lamp. tecMax*: the largest TEC among cells with any
    observation (flag 1 or more; a flag-0 value is the model's). anomalyThirdFraction: |anomaly| / median (median =
    TEC - anomaly) of the THIRD-largest well-observed cell with a median of at least 10 TECU, so one odd cell
    cannot light the lamp; None when fewer than three cells qualify."""
    tec, anom, flag, nLon = record['tec'], record['anom'], record['q'], record['nLon']
    best = None
    fractions = []
    for i, t in enumerate(tec):
        if t is None or not flag[i]:
            continue
        if best is None or t > tec[best]:
            best = i
        a = anom[i]
        if a is not None and flag[i] >= TEC_SUMMARY_MIN_FLAG and (t - a) / 10 >= TEC_SUMMARY_MIN_MEDIAN:
            fractions.append(abs(a) / (t - a))
    fractions.sort(reverse=True)
    out = {'validUtc': record['validUtc'], 'cellsCounted': len(fractions),
           'anomalyThirdFraction': round(fractions[2], 3) if len(fractions) >= 3 else None,
           'anomalyLargestFraction': round(fractions[0], 3) if fractions else None,
           'tecMaxObserved': None}
    if best is not None:
        row, col = divmod(best, nLon)
        out['tecMaxObserved'] = {'tec': tec[best] / 10, 'lat': record['latMin'] + row * record['latStep'],
                                 'lon': record['lonMin'] + col * record['lonStep'], 'flag': flag[best]}
    return out


def handle_weather_tec_summary(start_response):
    try:
        best = tec_newest_glotec()
    except (OSError, sqlite3.Error):
        return json_response(start_response, '503 Service Unavailable', {'error': 'Weather data unavailable'})
    if best is None:
        return json_response(start_response, '404 Not Found', {'error': 'no GloTEC map held yet'})
    if _tec_summary_cache.get('validUtc') != best[0]:
        _tec_summary_cache.clear()
        _tec_summary_cache.update(validUtc=best[0], payload=tec_summary_of(tec_unpack(best[1])))
    return json_response(start_response, '200 OK', _tec_summary_cache['payload'])


# ABOUT > USAGE: logins per city and per week, from databases/inboxUsage.db,
# table logins(day, city, country, latitude, longitude, logins) -- one row per
# day and city, counts only, no individual addresses. Until that database or
# table exists the answer is empty, not an error. Read-only.
def usage_summary():
    path = dbPaths.dbPath(dbPaths.USAGE_DB)
    empty = {'total': 0, 'cities': [], 'weeks': []}
    if not os.path.exists(path):
        return empty
    conn = sqlite3.connect(pathlib.Path(path).as_uri() + '?mode=ro', uri=True)
    try:
        cities = [{'city': city, 'country': country, 'latitude': latitude, 'longitude': longitude, 'logins': logins}
                  for city, country, latitude, longitude, logins in conn.execute(
                      'SELECT city, country, latitude, longitude, SUM(logins) AS total FROM logins '
                      'GROUP BY city, country, latitude, longitude ORDER BY total DESC')]
        # The Monday of each login day's week, as a date.
        weeks = [{'weekStart': week, 'logins': logins} for week, logins in conn.execute(
            "SELECT date(day, '-6 days', 'weekday 1') AS week, SUM(logins) FROM logins GROUP BY week ORDER BY week")]
    except sqlite3.OperationalError:
        return empty
    finally:
        conn.close()
    return {'total': sum(city['logins'] for city in cities), 'cities': cities, 'weeks': weeks}


def handle_usage(start_response):
    try:
        return json_response(start_response, '200 OK', usage_summary())
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_status(start_response):
    """Data-freshness table for the landing page's control area: one row
    per data source -- last successful refresh, records changed by it, and
    the expected next sync."""
    try:
        rows = [status_row(spec) for spec in STATUS_SOURCES]
        payload = {'generatedUtc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'sources': rows}
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# GRD VIEW sky view: the fixed sky from databases/ingestionSkyCatalogue.db (built
# once by scripts/buildSkyCatalogue.py), read once and the JSON kept until
# the file changes; browser-cached (cached_json_response()). Compact
# arrays, positions in J2000 degrees:
#   stars           [raDeg, decDeg, mag, bv, name] -- bv/name null if absent
#   lines           one [[raDeg, decDeg], ...] polyline per constellation line
#   constellations  [name, labelRaDeg, labelDecDeg, rank]
#   milkyWay        [level, [[raDeg, decDeg], ...]] -- per level, ring 0 the
#                   outline and the rest holes; level 1 faintest, 5 brightest
#   deepSky         [name, type, raDeg, decDeg, mag, dimArcmin]
_sky_catalogue_cache = {}


def sky_catalogue_payload():
    conn = site_db('sky')
    if conn is None:
        raise FileNotFoundError('no sky catalogue database')
    stars = [[r['raDeg'], r['decDeg'], r['mag'], r['bv'], r['name']]
             for r in conn.execute('SELECT raDeg, decDeg, mag, bv, name FROM skyStars ORDER BY mag')]
    lines = [json.loads(r['pointsJson'])
             for r in conn.execute('SELECT pointsJson FROM skyConstellationLines ORDER BY desig, lineIndex')]
    constellations = [[r['name'], r['labelRaDeg'], r['labelDecDeg'], r['rank']]
                      for r in conn.execute('SELECT name, labelRaDeg, labelDecDeg, rank FROM skyConstellations')]
    milky_way = [[r['level'], json.loads(r['pointsJson'])]
                 for r in conn.execute('SELECT level, pointsJson FROM skyMilkyWay ORDER BY level, ringIndex')]
    deep_sky = [[r['name'] or r['id'], r['type'], r['raDeg'], r['decDeg'], r['mag'], r['dimArcmin']]
                for r in conn.execute('SELECT id, name, type, raDeg, decDeg, mag, dimArcmin FROM skyDeepSky ORDER BY mag')]
    return {'stars': stars, 'lines': lines, 'constellations': constellations,
            'milkyWay': milky_way, 'deepSky': deep_sky}


def handle_sky_catalogue(environ, start_response):
    return cached_json_response(
        environ, start_response, _sky_catalogue_cache, sky_catalogue_payload,
        'sky', SKY_CATALOGUE_MAX_AGE_SEC,
        'Sky catalogue unavailable ({}); run scripts/buildSkyCatalogue.py')


# Browser caching for the GRD VIEW data (cached_json_response()): the
# browser reuses its copy for max-age seconds without asking at all (on a
# high-latency link even asking costs seconds), then asks whether it has
# changed, quoting the version (ETag) it holds; if not, the reply is a
# body-less 304. The version is the database files' modification times, so
# it changes exactly when a pipeline or GCAT run rewrites them.
SKY_CATALOGUE_MAX_AGE_SEC = 24 * 3600   # the fixed sky: rebuilt by hand, rarely
SKY_SATELLITES_MAX_AGE_SEC = 30 * 60    # orbital elements: refreshed every 12 hours


def cached_json_response(environ, start_response, cache, build, kind, max_age, error_text):
    """Serves build()'s JSON from `cache`, rebuilt when `kind`'s site
    database changes (site_version); gzipped when the browser accepts it;
    with ETag / Cache-Control, answering a matching If-None-Match with 304
    Not Modified."""
    try:
        key = site_version(kind)
        if cache.get('key') != key:
            body = json.dumps(build(), separators=(',', ':')).encode('utf-8')
            cache.update(key=key, json=body, gzip=gzip.compress(body, compresslevel=6),
                         etag='"' + '-'.join(str(mtime // 1_000_000_000) for _, _, mtime, _ in key) + '"')
    except (OSError, sqlite3.Error) as e:
        return json_response(start_response, '503 Service Unavailable', {'error': error_text.format(e)})
    use_gzip = 'gzip' in environ.get('HTTP_ACCEPT_ENCODING', '')
    # The two encodings are different bodies, so different versions.
    etag = cache['etag'][:-1] + ('-gz"' if use_gzip else '"')
    headers = [('Content-Type', 'application/json'), ('Vary', 'Accept-Encoding'),
               ('ETag', etag), ('Cache-Control', f'max-age={max_age}, must-revalidate')]
    if etag in [tag.strip() for tag in environ.get('HTTP_IF_NONE_MATCH', '').split(',')]:
        start_response('304 Not Modified', headers)
        return [b'']
    body = cache['gzip'] if use_gzip else cache['json']
    if use_gzip:
        headers.append(('Content-Encoding', 'gzip'))
    headers.append(('Content-Length', str(len(body))))
    start_response('200 OK', headers)
    return [body]


# GRD VIEW satellites: every payload and rocket body that could ever reach
# naked-eye brightness, with its orbital elements, for the browser's
# background calculation (assets/grdViewSatWorker.js). An object is kept
# if its best possible apparent magnitude -- at its perigee height, straight
# overhead, fully lit (1.24 brighter than the half-lit standard magnitude) --
# is VISIBLE_LIMIT_MAG or brighter: standard + 5 log10(perigee / 1000 km)
# - 1.24. That drops debris and unknown objects (no brightness estimate,
# by design) and almost everything in high orbits, before anything is sent.
# Brightness from ingestionGCAT.db gcatBrightness (scripts/estimateBrightness.py).
# Rebuilt when either database file changes (every pipeline / GCAT run).
# Compact rows, with no names or other details -- those are fetched one
# object at a time when needed (api/sky/object):
#   [noradID, kind ('P' payload / 'R' rocket body), stdMag, active (0/1),
#    spacex (0/1), epoch, meanMotion, eccentricity, inclination,
#    raOfAscNode, argOfPericenter, meanAnomaly, bstar, meanMotionDot,
#    meanMotionDdot, station (0/1: a station or visiting vehicle, in
#    CelesTrak's stations list -- excluded by GRD VIEW's SAT ONLY filter)]
# Numbers are rounded to what SGP4 needs (epoch to the second, angles to
# 1e-4 degree, mean motion to 1e-8 rev/day, drag terms to 4-5 figures).
VISIBLE_LIMIT_MAG = 5.0   # realistic naked-eye limit for a moving point under a good dark sky
_sky_satellites_cache = {}


def sky_satellites_payload():
    gcat = gcat_db()
    brightness = {r['noradID']: r['stdMag'] for r in gcat.execute(
        'SELECT noradID, stdMag FROM gcatBrightness WHERE stdMag IS NOT NULL')}
    spacex = {r['noradID'] for r in gcat.execute(
        f"SELECT noradID FROM gcatObjects WHERE noradID IS NOT NULL "
        f"AND ownerCode IN ({','.join('?' * len(SPACEX_ORG_CODES))})", SPACEX_ORG_CODES)}
    active = {r['noradID'] for r in site_db('orbital').execute(
        "SELECT noradID FROM orbital_object_groups WHERE groupName = 'active'")}
    stations = {r['noradID'] for r in site_db('orbital').execute(
        "SELECT noradID FROM orbital_object_groups WHERE groupName = 'stations'")}
    rows = []
    for r in site_db('orbital').execute(
            "SELECT noradID, name, objectType, perigee, epoch, meanMotion, eccentricity, inclination, "
            "raOfAscNode, argOfPericenter, meanAnomaly, bstar, meanMotionDot, meanMotionDdot "
            "FROM orbital_objects WHERE objectType IN ('PAY', 'R/B') "
            "AND (decayDate IS NULL OR decayDate = '') "
            "AND meanMotion IS NOT NULL AND epoch IS NOT NULL AND perigee > 0"):
        std = brightness.get(r['noradID'])
        if std is None or std + 5 * math.log10(r['perigee'] / 1000) - 1.24 > VISIBLE_LIMIT_MAG:
            continue
        name = r['name'] or ''
        rows.append([r['noradID'], 'P' if r['objectType'] == 'PAY' else 'R', round(std, 1),
                     int(r['noradID'] in active),
                     int(r['noradID'] in spacex or name.upper().startswith('STARLINK')),
                     r['epoch'][:19], round(r['meanMotion'], 8), round(r['eccentricity'], 7),
                     round(r['inclination'], 4), round(r['raOfAscNode'], 4),
                     round(r['argOfPericenter'], 4), round(r['meanAnomaly'], 4),
                     significant(r['bstar'], 5), significant(r['meanMotionDot'], 5),
                     significant(r['meanMotionDdot'], 4), int(r['noradID'] in stations)])
    return rows


def significant(value, figures):
    return float(f'{value:.{figures - 1}e}') if value else 0


# One object's details for GRD VIEW (a clicked satellite, or a label's
# name): catalogue facts from orbitalObjects.db, ownership, maker and size
# from GCAT, and the brightness estimate with its source.
def handle_sky_object(query_params, start_response):
    try:
        norad_id = int(get_param(query_params, 'noradID') or '')
    except ValueError:
        return json_response(start_response, '400 Bad Request', {'error': 'noradID must be a number'})
    try:
        row = site_db('orbital').execute(
            "SELECT noradID, name, objectType, owner, launchDate, launchSite, perigee, apogee, "
            "inclination, period, rcsSize, downlinkBand FROM orbital_objects WHERE noradID = ?",
            (norad_id,)).fetchone()
        if row is None:
            return json_response(start_response, '404 Not Found', {'error': f'No object {norad_id}'})
        details = dict(row)
        extra = gcat_db().execute(
            "SELECT o.name AS gcatName, o.owners, o.stateCode, o.manufacturer, o.bus, o.massKg, "
            "o.lengthM, o.diameterM, o.spanM, b.stdMag, b.source AS brightnessSource "
            "FROM gcatObjects o LEFT JOIN gcatBrightness b ON b.noradID = o.noradID "
            "WHERE o.noradID = ?", (norad_id,)).fetchone()
        if extra:
            details.update(dict(extra))
        return json_response(start_response, '200 OK', details)
    except sqlite3.Error as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_sky_satellites(environ, start_response):
    return cached_json_response(
        environ, start_response, _sky_satellites_cache, sky_satellites_payload,
        'orbital', SKY_SATELLITES_MAX_AGE_SEC,
        'Satellite data unavailable ({})')


# ON-ORBIT figures are stored for every combination of these two filters
# (scripts/orbitStats.py); a missing or unrecognised value falls back to the
# default rather than erroring.
ON_ORBIT_STATUS_FILTERS = ('active', 'all')
ON_ORBIT_KIND_FILTERS = ('satellites', 'spacecraft', 'objects')
# Charts only (orbitStats.py SPACEX_FILTERS): the regime table shows both.
ON_ORBIT_SPACEX_FILTERS = ('with', 'without')


def on_orbit_filters(query_params):
    status = get_param(query_params, 'status')
    kind = get_param(query_params, 'kind')
    return (status if status in ON_ORBIT_STATUS_FILTERS else ON_ORBIT_STATUS_FILTERS[0],
            kind if kind in ON_ORBIT_KIND_FILTERS else ON_ORBIT_KIND_FILTERS[0])


def on_orbit_spacex_filter(query_params):
    spacex = get_param(query_params, 'spacex')
    return spacex if spacex in ON_ORBIT_SPACEX_FILTERS else ON_ORBIT_SPACEX_FILTERS[0]


def stats_rows(sql, params):
    """Rows from onOrbitStats.db, or [] until it (or the table) exists."""
    conn = stats_db()
    if conn is None:
        return []
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        if 'no such table' in str(e):
            return []
        raise


def handle_on_orbit_nationality(query_params, start_response):
    """ON-ORBIT overview's nationality chart: payloads in orbit by state for
    ?status=active|all&kind=satellites|spacecraft (default active,
    satellites), as stored by scripts/orbitStats.py (storeNationality)."""
    try:
        status, kind = on_orbit_filters(query_params)
        spacex = on_orbit_spacex_filter(query_params)
        rows = stats_rows('SELECT label, stateCode, payloads FROM onOrbitNationality '
                          'WHERE statusFilter = ? AND kindFilter = ? AND spacexFilter = ? ORDER BY rank',
                          (status, kind, spacex))
        payload = {
            'status': status, 'kind': kind, 'spacex': spacex,
            'rows': [{'label': r['label'], 'stateCode': r['stateCode'], 'payloads': r['payloads']} for r in rows],
            'totalPayloads': sum(r['payloads'] for r in rows),
        }
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_on_orbit_regimes(query_params, start_response):
    """ON-ORBIT control-area table: payloads in orbit per CURRENT orbit regime
    (VLEO / LEO / MEO / GEO / > GEO, plus 'unclassified' -- no current orbit
    on file), all and excluding SpaceX, for the same filters -- stored by
    scripts/orbitStats.py (storeRegimes)."""
    try:
        status, kind = on_orbit_filters(query_params)
        rows = stats_rows('SELECT regime, allPayloads, exclSpacex FROM onOrbitRegimes '
                          'WHERE statusFilter = ? AND kindFilter = ? ORDER BY sortOrder', (status, kind))
        payload = {'status': status, 'kind': kind,
                   'rows': [{'regime': r['regime'], 'all': r['allPayloads'], 'exclSpacex': r['exclSpacex']}
                            for r in rows]}
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_on_orbit_inclination(query_params, start_response):
    """ON-ORBIT inclination histogram: payloads in orbit per 5-degree bucket
    of CURRENT inclination, 0-180 (every bucket, empty ones included), plus
    the number with no inclination on file, for the same filters -- stored
    by scripts/orbitStats.py (storeInclination)."""
    try:
        status, kind = on_orbit_filters(query_params)
        spacex = on_orbit_spacex_filter(query_params)
        rows = stats_rows('SELECT bucketStart, bucketEnd, payloads FROM onOrbitInclination '
                          'WHERE statusFilter = ? AND kindFilter = ? AND spacexFilter = ? ORDER BY bucketStart',
                          (status, kind, spacex))
        payload = {
            'status': status, 'kind': kind, 'spacex': spacex,
            'buckets': [{'from': r['bucketStart'], 'to': r['bucketEnd'], 'payloads': r['payloads']}
                        for r in rows if r['bucketStart'] is not None],
            'noInclination': sum(r['payloads'] for r in rows if r['bucketStart'] is None),
        }
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_on_orbit_sector(query_params, start_response):
    """ON-ORBIT sector pie: payloads in orbit per GCAT sector class -- A
    academic/amateur, B commercial, C civil government, D defence, plus
    'unknown' -- for the same three filters, as stored by
    scripts/orbitStats.py (storeSector)."""
    try:
        status, kind = on_orbit_filters(query_params)
        spacex = on_orbit_spacex_filter(query_params)
        rows = stats_rows('SELECT sector, payloads FROM onOrbitSector '
                          'WHERE statusFilter = ? AND kindFilter = ? AND spacexFilter = ? ORDER BY sortOrder',
                          (status, kind, spacex))
        payload = {'status': status, 'kind': kind, 'spacex': spacex,
                   'rows': [{'sector': r['sector'], 'payloads': r['payloads']} for r in rows]}
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


ON_ORBIT_OWNERS_MAX = 200   # more than any screen can show; the page picks how many


def handle_on_orbit_owners(query_params, start_response):
    """ON-ORBIT owners chart: the largest owners by payloads in orbit (first
    ON_ORBIT_OWNERS_MAX, ranked), plus totals over ALL owners -- how many
    owners, how many payloads have one, how many don't -- for the same three
    filters, as stored by scripts/orbitStats.py (storeOwners)."""
    try:
        status, kind = on_orbit_filters(query_params)
        spacex = on_orbit_spacex_filter(query_params)
        params = (status, kind, spacex)
        where = 'WHERE statusFilter = ? AND kindFilter = ? AND spacexFilter = ?'
        rows = stats_rows(f'SELECT ownerCode, label, fullName, stateCode, payloads FROM onOrbitOwners {where} '
                          f'AND rank > 0 ORDER BY rank LIMIT {ON_ORBIT_OWNERS_MAX}', params)
        totals = stats_rows(f'SELECT COUNT(*) AS owners, COALESCE(SUM(payloads), 0) AS payloads FROM onOrbitOwners '
                            f'{where} AND rank > 0', params)
        noOwner = stats_rows(f'SELECT payloads FROM onOrbitOwners {where} AND rank = 0', params)
        payload = {
            'status': status, 'kind': kind, 'spacex': spacex,
            'rows': [{'code': r['ownerCode'], 'label': r['label'], 'fullName': r['fullName'],
                      'stateCode': r['stateCode'], 'payloads': r['payloads']} for r in rows],
            'totalOwners': totals[0]['owners'] if totals else 0,
            'ownedPayloads': totals[0]['payloads'] if totals else 0,
            'noOwner': noOwner[0]['payloads'] if noOwner else 0,
        }
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# GCAT organisation codes for SpaceX (as scripts/orbitStats.py): W/O SPACEX
# on the LAUNCHES charts leaves out launches SpaceX carried out (launch
# agency) and objects SpaceX owns.
SPACEX_ORG_CODES = ('SPX', 'SPXES', 'SPXS', 'SPXT', 'SPXTX')
# ?outcome=all|success on the launch-log charts: every attempt, or only those
# GCAT records as successful (second letter of the launch code S).
LAUNCH_OUTCOME_FILTERS = ('all', 'success')


def launch_log_where(query_params):
    """(spacex, outcome, WHERE clause, params) shared by the launch-log
    endpoints: orbital and deep-space attempts, less SpaceX's / failures as
    the filters say."""
    spacex = on_orbit_spacex_filter(query_params)
    outcome = get_param(query_params, 'outcome')
    outcome = outcome if outcome in LAUNCH_OUTCOME_FILTERS else LAUNCH_OUTCOME_FILTERS[0]
    where = "substr(launchCode, 1, 1) IN ('O', 'D') AND launchDate IS NOT NULL"
    params = ()
    if spacex == 'without':
        where += f" AND COALESCE(agency, '') NOT IN ({','.join('?' * len(SPACEX_ORG_CODES))})"
        params = SPACEX_ORG_CODES
    if outcome == 'success':
        where += " AND substr(launchCode, 2, 1) = 'S'"
    return spacex, outcome, where, params


def handle_launches_per_year(query_params, start_response):
    """LAUNCHES line chart: orbital and deep-space launch attempts per year
    (GCAT launch codes O* and D*, successes and failures; suborbital N*/X*
    tests left out), from ingestionGCAT.db's launch log -- one row per payload, so
    launches are counted by distinct launch tag. Counted on request: a few
    tens of thousands of rows."""
    try:
        spacex, outcome, where, params = launch_log_where(query_params)
        conn = gcat_db()
        rows = []
        latest = None
        if conn is not None:
            rows = conn.execute(
                # The launch log has one row per payload, so COUNT(*) is the
                # payloads those launches carried (including any lost).
                "SELECT substr(launchDate, 1, 4) AS year, COUNT(DISTINCT launchTag) AS launches, "
                "COUNT(*) AS payloads, "
                "COUNT(DISTINCT CASE WHEN substr(launchCode, 2, 1) = 'F' THEN launchTag END) AS failures "
                f"FROM gcatLaunches WHERE {where} GROUP BY year ORDER BY year", params).fetchall()
            latest = conn.execute(f"SELECT MAX(launchDate) FROM gcatLaunches WHERE {where}", params).fetchone()[0]
        payload = {
            'spacex': spacex,
            'outcome': outcome,
            'rows': [{'year': r['year'], 'launches': r['launches'], 'payloads': r['payloads'],
                      'failures': r['failures']} for r in rows],
            'latestLaunch': latest,
        }
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# Launch-vehicle country (GCAT lvState) -> chart series, in stacking order.
# European launchers are one series; GCAT codes Rocket Lab's Electron as NZ.
LAUNCH_COUNTRY_SERIES = ['US', 'SU', 'RU', 'CN', 'EU', 'J', 'IN', 'NZ', 'other']
LAUNCH_COUNTRY_GROUPS = {'F': 'EU', 'I-ESA': 'EU', 'I-ELDO': 'EU', 'I': 'EU', 'D': 'EU', 'UK': 'EU'}


def handle_launches_by_country(query_params, start_response):
    """LAUNCHES stacked bar chart: orbital and deep-space launch attempts per
    year by launch-vehicle country (LAUNCH_COUNTRY_SERIES), counted on
    request from ingestionGCAT.db's launch log; W/O SPACEX leaves out SpaceX's."""
    try:
        spacex, outcome, where, params = launch_log_where(query_params)
        conn = gcat_db()
        counts = {}
        if conn is not None:
            for r in conn.execute("SELECT CAST(substr(launchDate, 1, 4) AS INTEGER) AS year, lvState, "
                                  f"COUNT(DISTINCT launchTag) AS launches FROM gcatLaunches WHERE {where} "
                                  "GROUP BY year, lvState", params):
                state = r['lvState'] or ''
                series = LAUNCH_COUNTRY_GROUPS.get(state, state if state in LAUNCH_COUNTRY_SERIES else 'other')
                key = (r['year'], series)
                counts[key] = counts.get(key, 0) + r['launches']
        years = sorted({year for year, _ in counts})
        rows = [{'year': year, 'country': series, 'launches': counts.get((year, series), 0)}
                for year in years for series in LAUNCH_COUNTRY_SERIES]
        return json_response(start_response, '200 OK', {'spacex': spacex, 'outcome': outcome, 'rows': rows})
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_launches_payloads_launched(query_params, start_response):
    """LAUNCHES stacked area chart: new payloads reaching orbit each year (this
    year: to date), Starlink separately and the rest by GCAT sector -- stored
    by scripts/orbitStats.py (storeLaunchHistory)."""
    try:
        spacex = on_orbit_spacex_filter(query_params)
        rows = stats_rows('SELECT year, series, payloads FROM launchPayloadsLaunched WHERE spacexFilter = ? '
                          'ORDER BY year, sortOrder', (spacex,))
        return json_response(start_response, '200 OK', {
            'spacex': spacex,
            'rows': [{'year': r['year'], 'series': r['series'], 'payloads': r['payloads']} for r in rows]})
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_launches_reentries(query_params, start_response):
    """LAUNCHES stacked bar chart: objects that came back down each year
    (re-entered, de-orbited or landed), by payload / rocket body / debris /
    other -- stored by scripts/orbitStats.py (storeLaunchHistory)."""
    try:
        spacex = on_orbit_spacex_filter(query_params)
        rows = stats_rows('SELECT year, kind, objects FROM launchReentries WHERE spacexFilter = ? '
                          'ORDER BY year, sortOrder', (spacex,))
        return json_response(start_response, '200 OK', {
            'spacex': spacex,
            'rows': [{'year': r['year'], 'kind': r['kind'], 'objects': r['objects']} for r in rows]})
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# --- ON-ORBIT group charts, counted on request ---------------------------------------
# From onOrbitStats.db's onOrbitObjects (one row per object in orbit, written
# by scripts/orbitStats.py storeObjectTable), with the page's three filters
# applied in SQL. Each chart: a query returning rows; the page draws them.
ON_ORBIT_REGIMES = ['VLEO', 'LEO', 'MEO', 'GEO', '> GEO', 'HEO']
ON_ORBIT_ALL_OBJECT_CHARTS = ('catalogue-by-type', 'debris-altitude', 'debris-inclination', 'debris-history',
                              'rocket-bodies-country', 'rocket-bodies-vehicle', 'debris-origin')


def on_orbit_object_where(status, kind, spacex, ignore_status=False):
    clauses = []
    if status == 'active' and not ignore_status:
        clauses.append('active = 1')
    if kind == 'satellites':
        clauses.append('satellite = 1')
    elif kind == 'spacecraft':
        clauses.append('payload = 1')
    if spacex == 'without':
        clauses.append('spacex = 0')
    return ('WHERE ' + ' AND '.join(clauses)) if clauses else ''


def on_orbit_chart_rows(name, status, kind, spacex):
    """Rows for one group chart, or None for an unknown name."""
    where = on_orbit_object_where(status, kind, spacex)
    andWhere = (where + ' AND') if where else 'WHERE'
    queries = {
        # LOCN
        'inclination-by-regime': f"SELECT MIN(CAST(inclination / 5 AS INTEGER) * 5, 175) AS band, regime, "
                                 f"COUNT(*) AS n FROM onOrbitObjects {andWhere} inclination IS NOT NULL "
                                 f"AND regime IS NOT NULL GROUP BY band, regime",
        'altitude': f"SELECT CAST(meanAltitudeKm / 25 AS INTEGER) * 25 AS band, COUNT(*) AS n FROM onOrbitObjects "
                    f"{andWhere} meanAltitudeKm < 2000 AND meanAltitudeKm >= 0 GROUP BY band",
        # WEATHER > LEO DRAG, "who is exposed": active payloads in 10 km bands of mean altitude, SpaceX apart (the
        # status, kind and SpaceX buttons of ON-ORBIT do not apply here)
        'exposure': "SELECT CAST(meanAltitudeKm / 10 AS INTEGER) * 10 AS band, spacex, COUNT(*) AS n FROM onOrbitObjects "
                    "WHERE active = 1 AND payload = 1 AND meanAltitudeKm >= 150 AND meanAltitudeKm < 700 GROUP BY band, spacex",
        'altitude-vs-inclination': f"SELECT CAST(meanAltitudeKm / 25 AS INTEGER) * 25 AS alt, "
                                   f"CAST(inclination AS INTEGER) AS inc, sector, COUNT(*) AS n FROM onOrbitObjects "
                                   f"{andWhere} meanAltitudeKm < 2000 AND meanAltitudeKm >= 0 "
                                   f"AND inclination IS NOT NULL GROUP BY alt, inc, sector",
        'geo-belt': f"SELECT CAST((geoLongitude + 180) / 2 AS INTEGER) * 2 - 180 AS band, sector, COUNT(*) AS n "
                    f"FROM onOrbitObjects {andWhere} regime = 'GEO' AND geoLongitude IS NOT NULL "
                    f"GROUP BY band, sector",
        'active-by-regime': f"SELECT regime, active, COUNT(*) AS n FROM onOrbitObjects "
                            f"{on_orbit_object_where(status, kind, spacex, ignore_status=True) or 'WHERE 1'} "
                            f"AND regime IS NOT NULL GROUP BY regime, active",
        'age': f"SELECT MIN(CAST(strftime('%Y', 'now') AS INTEGER) - launchYear, 30) AS band, regime, "
               f"COUNT(*) AS n FROM onOrbitObjects {andWhere} launchYear IS NOT NULL AND regime IS NOT NULL "
               f"GROUP BY band, regime",
        # COMMERCIAL
        'mission': f"SELECT COALESCE(category, 'none') AS category, COUNT(*) AS n FROM onOrbitObjects {where} "
                   f"GROUP BY 1",
        'sector-by-country': f"SELECT COALESCE(stateCode, '') AS state, sector, COUNT(*) AS n FROM onOrbitObjects "
                             f"{where} GROUP BY state, sector",
        'manufacturers': f"SELECT manufacturerCode AS code, manufacturerName AS name, COUNT(*) AS n "
                         f"FROM onOrbitObjects {andWhere} manufacturerCode IS NOT NULL AND manufacturerCode <> 'UNK' "
                         f"GROUP BY code ORDER BY n DESC LIMIT 20",
        'buses': f"SELECT bus, COUNT(*) AS n FROM onOrbitObjects {andWhere} bus IS NOT NULL "
                 f"GROUP BY bus ORDER BY n DESC LIMIT 20",
    }
    # DEBRIS: every object in orbit -- the status and kind buttons don't
    # apply (debris is never active, and isn't a payload); SpaceX does.
    everything = on_orbit_object_where('all', 'objects', spacex)
    andEverything = (everything + ' AND') if everything else 'WHERE'
    queries.update({
        'catalogue-by-type': f"SELECT regime, objectType, COUNT(*) AS n FROM onOrbitObjects {andEverything} "
                             f"regime IS NOT NULL GROUP BY regime, objectType",
        'debris-altitude': f"SELECT CAST(meanAltitudeKm / 25 AS INTEGER) * 25 AS band, objectType, COUNT(*) AS n "
                           f"FROM onOrbitObjects {andEverything} meanAltitudeKm < 2000 AND meanAltitudeKm >= 0 "
                           f"GROUP BY band, objectType",
        'debris-inclination': f"SELECT MIN(CAST(inclination / 5 AS INTEGER) * 5, 175) AS band, COUNT(*) AS n "
                              f"FROM onOrbitObjects {andEverything} objectType = 'DEB' AND inclination IS NOT NULL "
                              f"GROUP BY band",
        'rocket-bodies-country': f"SELECT COALESCE(stateCode, '') AS state, COUNT(*) AS n FROM onOrbitObjects "
                                 f"{andEverything} objectType = 'R/B' GROUP BY state ORDER BY n DESC",
        'rocket-bodies-vehicle': f"SELECT COALESCE(launchVehicle, '') AS vehicle, COUNT(*) AS n FROM onOrbitObjects "
                                 f"{andEverything} objectType = 'R/B' GROUP BY vehicle ORDER BY n DESC",
        'debris-origin': f"SELECT COALESCE(parentJcat, '') AS parent, parentName AS name, "
                         f"parentLaunchYear AS year, COUNT(*) AS n FROM onOrbitObjects {andEverything} "
                         f"objectType = 'DEB' GROUP BY parent ORDER BY n DESC",
        # COMMS: all three buttons apply.
        'band': f"SELECT COALESCE(downlinkBand, 'none') AS band, COUNT(*) AS n FROM onOrbitObjects {where} "
                f"GROUP BY 1",
        'band-by-mission': f"SELECT downlinkBand AS band, COALESCE(category, 'none') AS category, COUNT(*) AS n "
                           f"FROM onOrbitObjects {andWhere} downlinkBand IS NOT NULL GROUP BY band, category",
        'band-by-regime': f"SELECT downlinkBand AS band, regime, COUNT(*) AS n FROM onOrbitObjects {andWhere} "
                          f"downlinkBand IS NOT NULL AND regime IS NOT NULL GROUP BY band, regime",
        # COMMERCIAL: the country -> owner tree.
        'country-owner': f"SELECT COALESCE(stateCode, '') AS state, COALESCE(ownerCode, '') AS owner, "
                         f"COALESCE(ownerName, ownerCode, '') AS ownerName, COUNT(*) AS n FROM onOrbitObjects "
                         f"{where} GROUP BY state, owner",
    })
    if name == 'debris-history':
        return stats_rows('SELECT year, created, reentered, inOrbit FROM onOrbitDebrisByYear '
                          'WHERE spacexFilter = ? ORDER BY year', (spacex,))
    if name == 'payloads-by-year':
        return stats_rows('SELECT year, sector, payloads AS n FROM onOrbitPayloadsByYear WHERE spacexFilter = ? '
                          'ORDER BY year, sortOrder', (spacex,))
    if name not in queries:
        return None
    return stats_rows(queries[name], ())


def handle_on_orbit_chart(query_params, start_response):
    """ON-ORBIT group charts (LOCN, COMMERCIAL): ?name=<chart> plus the usual
    status / kind / spacex filters. Returns {name, status, kind, spacex,
    rows, total} -- total being the objects the filters select, for the
    title bars -- plus, for country charts, display names."""
    try:
        status, kind = on_orbit_filters(query_params)
        spacex = on_orbit_spacex_filter(query_params)
        name = get_param(query_params, 'name') or ''
        rows = on_orbit_chart_rows(name, status, kind, spacex)
        if rows is None:
            return json_response(start_response, '404 Not Found', {'error': f'unknown chart {name!r}'})
        # DEBRIS charts count every object (status and kind don't apply).
        if name in ON_ORBIT_ALL_OBJECT_CHARTS:
            where = on_orbit_object_where('all', 'objects', spacex)
        else:
            where = on_orbit_object_where(status, kind, spacex)
        total = stats_rows(f'SELECT COUNT(*) AS n FROM onOrbitObjects {where}', ())
        payload = {
            'name': name, 'status': status, 'kind': kind, 'spacex': spacex,
            'rows': [dict(r) for r in rows],
            'total': total[0]['n'] if total else 0,
        }
        if name in ('sector-by-country', 'rocket-bodies-country', 'country-owner'):
            conn = gcat_db()
            states = {r['state'] for r in rows if r['state']}
            payload['stateNames'] = {}
            if conn is not None and states:
                found = conn.execute(f"SELECT code, shortName, name FROM gcatOrgs WHERE code IN "
                                     f"({','.join('?' * len(states))})", tuple(states)).fetchall()
                payload['stateNames'] = {r['code']: r['shortName'] or r['name'] for r in found}
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_news_topic_counts(start_response):
    """Per-topic article totals for the news control panel histogram --
    precomputed by scripts/tagNews.py on every refresh, so this is a plain
    read rather than a count over articleTopics on every page load."""
    try:
        try:
            rows = site_db('news').execute('SELECT topic, articleCount, updatedAt FROM newsTopicCounts').fetchall()
        except sqlite3.OperationalError as e:
            # Not tagged yet since this was deployed -- no counts to show.
            if 'no such table' in str(e):
                rows = []
            else:
                raise
        payload = {
            'counts': {row['topic']: row['articleCount'] for row in rows},
            'updatedAt': max((row['updatedAt'] for row in rows), default=None),
        }
        return json_response(start_response, '200 OK', payload)
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_ground_segment_assets(start_response):
    try:
        rows = site_db('groundSegment').execute('SELECT * FROM ground_segment_assets').fetchall()
        return json_response(start_response, '200 OK', rows_to_dicts(rows))
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# Fetches specific orbital objects by NORAD ID, for the on-orbit panel's
# plotted-objects list. One batched request for the whole list, not one per
# object.
def handle_orbital_objects(query_params, start_response):
    try:
        ids_param = get_param(query_params, 'ids') or ''
        norad_ids = []
        for s in ids_param.split(','):
            s = s.strip()
            try:
                norad_ids.append(int(s))
            except ValueError:
                continue

        if not norad_ids:
            return json_response(start_response, '200 OK', [])

        placeholders = ','.join('?' * len(norad_ids))
        rows = site_db('orbital').execute(
            f'SELECT noradID, name, objectID, epoch, meanMotion, eccentricity, inclination, raOfAscNode, argOfPericenter, meanAnomaly, bstar, meanMotionDot, meanMotionDdot, objectType, owner, launchDate, launchSite, decayDate, rcsSize, period, apogee, perigee, source, downlinkBand, eirpDbw, eirpSource FROM orbital_objects WHERE noradID IN ({placeholders})',
            norad_ids,
        ).fetchall()
        return json_response(start_response, '200 OK', rows_to_dicts(rows))
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# All active payloads with usable mean elements, for the GS OPS panel's
# VISIBLE NOW feature (client-side SGP4 + look-angle against the ground
# station). One bulk read -- ~19k rows -- fetched once per session and
# cached client-side: the OMM fields json2satrec() needs, the handful
# shown in the click popup (name/owner/launchDate/objectType), and the
# enrichEirp / ingestSatnogsRf columns the client-side link budget uses
# (downlink EIRP, satellite G/T, downlink/uplink frequency, mode/baud).
# Restricted to objectType 'PAY' (rocket bodies and debris aren't
# "satellites" a station tasks) and decayDate IS NULL.
def handle_active_orbital_objects(start_response):
    try:
        rows = site_db('orbital').execute(
            "SELECT noradID, name, owner, launchDate, launchSite, objectType, "
            "period, apogee, perigee, rcsSize, downlinkBand, eirpDbw, eirpSource, "
            "satRxGainDbi, satNoiseTempK, satGtDbk, satGtSource, "
            "dlFreqHz, ulFreqHz, dlBandwidthHz, rfMode, rfBaud, rfSource, "
            "epoch, meanMotion, "
            "eccentricity, inclination, raOfAscNode, argOfPericenter, meanAnomaly, "
            "bstar, meanMotionDot, meanMotionDdot "
            "FROM orbital_objects "
            "WHERE objectType = 'PAY' AND decayDate IS NULL "
            "AND meanMotion IS NOT NULL AND epoch IS NOT NULL"
        ).fetchall()
        return json_response(start_response, '200 OK', rows_to_dicts(rows))
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# Non-payload objects (rocket bodies + debris) with usable elements, for
# the GS OPS status panel's "objects in view" total only -- these are
# propagated client-side for a count, never plotted or link-budgeted, so
# just the OMM element fields json2satrec() needs (no name / metadata / RF
# columns). ~13k rows.
def handle_active_nonpayload_objects(start_response):
    try:
        rows = site_db('orbital').execute(
            "SELECT noradID, epoch, meanMotion, eccentricity, inclination, "
            "raOfAscNode, argOfPericenter, meanAnomaly, bstar, "
            "meanMotionDot, meanMotionDdot "
            "FROM orbital_objects "
            "WHERE objectType IN ('R/B', 'DEB') AND decayDate IS NULL "
            "AND meanMotion IS NOT NULL AND epoch IS NOT NULL"
        ).fetchall()
        return json_response(start_response, '200 OK', rows_to_dicts(rows))
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_filter_options(start_response):
    try:
        owners = [r['owner'] for r in site_db('orbital').execute(
            'SELECT DISTINCT owner FROM orbital_objects WHERE owner IS NOT NULL ORDER BY owner'
        ).fetchall()]
        groups = [r['groupName'] for r in site_db('orbital').execute(
            'SELECT DISTINCT groupName FROM orbital_object_groups ORDER BY groupName'
        ).fetchall()]
        launch_sites = [r['launchSite'] for r in site_db('orbital').execute(
            'SELECT DISTINCT launchSite FROM orbital_objects WHERE launchSite IS NOT NULL ORDER BY launchSite'
        ).fetchall()]
        return json_response(start_response, '200 OK', {
            'owners': owners, 'groups': groups, 'launchSites': launch_sites,
        })
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


def handle_orbital_objects_search(query_params, start_response):
    try:
        name = get_param(query_params, 'name')
        norad_id = get_param(query_params, 'noradId')
        owner = get_param(query_params, 'owner')
        object_type = get_param(query_params, 'objectType')
        group = get_param(query_params, 'group')
        altitude_regime = get_param(query_params, 'altitudeRegime')
        inclination_band = get_param(query_params, 'inclinationBand')
        mean_motion_from = get_float_param(query_params, 'meanMotionFrom')
        mean_motion_to = get_float_param(query_params, 'meanMotionTo')
        launch_year_from = get_param(query_params, 'launchYearFrom')
        launch_year_to = get_param(query_params, 'launchYearTo')
        launch_site = get_param(query_params, 'launchSite')

        conditions = []
        params = []

        if group:
            conditions.append('o.noradID IN (SELECT noradID FROM orbital_object_groups WHERE groupName = ?)')
            params.append(group)
        if name:
            conditions.append('o.name LIKE ? COLLATE NOCASE')
            params.append(f'%{name}%')
        if norad_id:
            conditions.append('CAST(o.noradID AS TEXT) LIKE ?')
            params.append(f'%{norad_id}%')
        if owner:
            conditions.append('o.owner = ?')
            params.append(owner)
        if object_type:
            conditions.append('o.objectType = ?')
            params.append(object_type)
        if altitude_regime and altitude_regime in ALTITUDE_REGIME_SQL:
            conditions.append(ALTITUDE_REGIME_SQL[altitude_regime])
        if mean_motion_from is not None:
            conditions.append('o.meanMotion >= ?')
            params.append(mean_motion_from)
        if mean_motion_to is not None:
            conditions.append('o.meanMotion <= ?')
            params.append(mean_motion_to)
        if launch_year_from:
            conditions.append('substr(o.launchDate, 1, 4) >= ?')
            params.append(launch_year_from)
        if launch_year_to:
            conditions.append('substr(o.launchDate, 1, 4) <= ?')
            params.append(launch_year_to)
        if launch_site:
            conditions.append('o.launchSite = ?')
            params.append(launch_site)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ''

        # Most-recent-launch-first by default (NULL launchDate sorts last
        # under DESC in SQLite, so un-enriched objects fall to the end
        # rather than crowding out real dates) -- previously ORDER BY
        # noradID, which meant an unfiltered/default search only ever
        # showed the oldest ~500 cataloged objects.
        rows = site_db('orbital').execute(
            f'SELECT o.noradID, o.name, o.objectID, o.epoch, o.meanMotion, o.eccentricity, o.inclination, o.raOfAscNode, o.argOfPericenter, o.meanAnomaly, o.bstar, o.meanMotionDot, o.meanMotionDdot, o.objectType, o.owner, o.launchDate, o.launchSite, o.decayDate, o.rcsSize, o.period, o.apogee, o.perigee, o.source, o.downlinkBand, o.eirpDbw, o.eirpSource FROM orbital_objects o {where_clause} ORDER BY o.launchDate DESC LIMIT ?',
            params + [RESULT_SCAN_LIMIT],
        ).fetchall()
        rows = rows_to_dicts(rows)

        if inclination_band and inclination_band in INCLINATION_BAND_RANGES:
            lo, hi = INCLINATION_BAND_RANGES[inclination_band]
            rows = [
                row for row in rows
                if row['inclination'] is not None and lo <= row['inclination'] <= hi
            ]

        truncated = len(rows) > RESULT_LIMIT or len(rows) == RESULT_SCAN_LIMIT
        objects = rows[:RESULT_LIMIT]

        return json_response(start_response, '200 OK', {'objects': objects, 'truncated': truncated})
    except Exception as e:
        return json_response(start_response, '500 Internal Server Error', {'error': str(e)})


# Only these are ever served as files: the page itself and everything under
# assets/. Anything else -- server.py, scripts/, databases/, setupCron.sh,
# spacetrack.env, tmp/ ... -- is a 404, as is any path that resolves outside
# assets/ (e.g. /assets/../server.py). An allowlist rather than a blocklist,
# so a new file type can't slip through (bug 7). On the live site the
# .htaccess rules refuse the same files before they reach this; this is the
# second layer, and the only one when running locally.
STATIC_ROOT_FILES = {'index.html'}
STATIC_DIR = os.path.realpath(os.path.join(BASE_DIR, 'assets'))


def static_file_path(path_info):
    """The file to serve for a request path, or None if it isn't one of the
    allowed static files."""
    rel_path = 'index.html' if path_info in ('', '/') else path_info.lstrip('/')
    if rel_path in STATIC_ROOT_FILES:
        return os.path.join(BASE_DIR, rel_path)
    if not rel_path.startswith('assets/'):
        return None
    try:
        file_path = os.path.realpath(os.path.join(BASE_DIR, rel_path))
    except ValueError:   # e.g. an embedded NUL
        return None
    if not file_path.startswith(STATIC_DIR + os.sep):
        return None
    return file_path


# Serves frontend static assets: "/" (and /index.html) is the page, anything
# else must be under assets/ (static_file_path). Content-type mapping only
# branches for .js/.css/.json, defaulting to text/html for anything else
# (including images/fonts) -- matches server.js exactly, quirk and all.
def handle_static(path_info, start_response):
    file_path = static_file_path(path_info)

    if file_path is None or not os.path.isfile(file_path):
        start_response('404 Not Found', [('Content-Type', 'text/plain')])
        return [b'404 Not Found']

    ext = os.path.splitext(file_path)[1]
    if ext == '.js':
        content_type = 'text/javascript'
    elif ext == '.css':
        content_type = 'text/css'
    elif ext == '.json':
        content_type = 'application/json'
    elif ext == '.svg':
        # Browsers won't render an SVG image (e.g. a CSS background) served as text/html.
        content_type = 'image/svg+xml'
    else:
        content_type = 'text/html'

    with open(file_path, 'rb') as f:
        content = f.read()

    start_response('200 OK', [
        ('Content-Type', content_type),
        ('Cache-Control', 'no-store'),
        ('Content-Length', str(len(content))),
    ])
    return [content]


# Tester bug reports: the BUG REPORT spine button's form (assets/bugReport.js)
# POSTs here, and each accepted report is appended to databases/
# inboxBugReports.db -- a folder deploys never touch, so reports survive them.
# Columns mirror the user-entered columns of bugsDB.xlsx, so triage is a
# copy into the workbook (0_tools/bugs.py add); the rest (Status, Root Cause,
# Date Fixed) stay the developers'. This is the only endpoint that writes,
# and it is public, so: a body size cap, every field validated here (the
# browser's checks are only a convenience), a hidden honeypot field bots
# fill in, and a rate limit per visitor (a salted hash of the IP -- the
# address itself is never stored) plus a global daily cap.
BUG_REPORT_DB = BUG_REPORTS_DB
# Which server a report came from. LIVE when Passenger imports this module;
# set to DEV below when it is run directly (python server.py). Decided by
# how the server was started, not guessed from the request's hostname.
SERVER_ROLE = 'LIVE'
BUG_REPORT_MAX_BODY = 16 * 1024
BUG_REPORT_PER_VISITOR_PER_HOUR = 5
BUG_REPORT_GLOBAL_PER_DAY = 200
BUG_REPORT_TYPES = ('Bug', 'Feature-Request')
BUG_REPORT_SEVERITIES = ('Low', 'Medium', 'High')
BUG_REPORT_COMPONENTS = (
    'Home page', 'NEWS', 'GRD-TRACK', 'ON-ORBIT', 'GS OPS', 'GRD VIEW', 'LAUNCHES',
    'GRND SGMNT', 'ORGANISATIONS', 'WEATHER', 'EO', 'ABOUT', 'ACKNOWLEDGMENTS', 'Whole site / other',   # ACKNOWLEDGMENTS: the old name
)
# field: (required, min length, max length). Choice fields are checked separately.
BUG_REPORT_TEXT_FIELDS = {
    'title': (True, 5, 120),
    'description': (True, 10, 2000),
    'stepsToReproduce': (False, 0, 2000),
    'expectedBehaviour': (False, 0, 1000),
    'actualBehaviour': (False, 0, 1000),
    'foundBy': (False, 0, 60),
}

_bug_db = None
_bug_db_lock = threading.Lock()  # one shared connection; the local dev server is threaded


def get_bug_db():
    global _bug_db
    if _bug_db is None:
        os.makedirs(DB_DIR, exist_ok=True)
        _bug_db = open_db(BUG_REPORT_DB)
        _bug_db.executescript('''
            CREATE TABLE IF NOT EXISTS bugReports (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                dateFound          TEXT NOT NULL,
                title              TEXT NOT NULL,
                bugOrFeature       TEXT NOT NULL,
                severity           TEXT NOT NULL,
                component          TEXT NOT NULL,
                description        TEXT NOT NULL,
                stepsToReproduce   TEXT,
                expectedBehaviour  TEXT,
                actualBehaviour    TEXT,
                foundBy            TEXT,
                server             TEXT NOT NULL,
                phase              TEXT NOT NULL,
                userAgent          TEXT,
                viewport           TEXT,
                visitorHash        TEXT NOT NULL,
                copiedToBugsDb     INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_bugReports_visitor ON bugReports(visitorHash, dateFound);
            CREATE TABLE IF NOT EXISTS bugReportMeta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        if not _bug_db.execute("SELECT 1 FROM bugReportMeta WHERE key = 'salt'").fetchone():
            _bug_db.execute("INSERT INTO bugReportMeta (key, value) VALUES ('salt', ?)", (os.urandom(16).hex(),))
        _bug_db.commit()
    return _bug_db


def validate_bug_report(data):
    """Returns (clean_fields, errors). errors maps field name -> message."""
    errors = {}
    clean = {}
    if not isinstance(data, dict):
        return clean, {'form': 'The report could not be read.'}
    for field, (required, min_len, max_len) in BUG_REPORT_TEXT_FIELDS.items():
        value = data.get(field, '')
        value = value.strip() if isinstance(value, str) else ''
        if required and not value:
            errors[field] = 'Required.'
        elif value and len(value) < min_len:
            errors[field] = f'At least {min_len} characters, please.'
        elif len(value) > max_len:
            errors[field] = f'At most {max_len} characters.'
        clean[field] = value or None
    for field, choices in (('bugOrFeature', BUG_REPORT_TYPES), ('severity', BUG_REPORT_SEVERITIES),
                           ('component', BUG_REPORT_COMPONENTS)):
        value = data.get(field)
        if value not in choices:
            errors[field] = 'Please choose one of the options.'
        clean[field] = value
    for field, max_len in (('userAgent', 300), ('viewport', 20)):
        value = data.get(field)
        clean[field] = value[:max_len] if isinstance(value, str) else None
    return clean, errors


def handle_bug_report(environ, start_response):
    try:
        length = int(environ.get('CONTENT_LENGTH') or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return json_response(start_response, '400 Bad Request', {'ok': False, 'errors': {'form': 'Empty report.'}})
    if length > BUG_REPORT_MAX_BODY:
        return json_response(start_response, '413 Payload Too Large', {'ok': False, 'errors': {'form': 'Report too long.'}})
    try:
        data = json.loads(environ['wsgi.input'].read(length).decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return json_response(start_response, '400 Bad Request', {'ok': False, 'errors': {'form': 'The report could not be read.'}})

    # Honeypot: a field hidden from people. Anything in it means a bot; it
    # gets the normal success reply so it learns nothing, and is not stored.
    if isinstance(data, dict) and data.get('website'):
        return json_response(start_response, '201 Created', {'ok': True})

    clean, errors = validate_bug_report(data)
    if errors:
        return json_response(start_response, '400 Bad Request', {'ok': False, 'errors': errors})

    with _bug_db_lock:
        return _store_bug_report(environ, start_response, clean)


def _store_bug_report(environ, start_response, clean):
    db = get_bug_db()
    salt = db.execute("SELECT value FROM bugReportMeta WHERE key = 'salt'").fetchone()[0]
    visitor = hashlib.sha256((salt + environ.get('REMOTE_ADDR', '')).encode('utf-8')).hexdigest()[:16]
    now = datetime.now(timezone.utc)
    hour_ago = (now - timedelta(hours=1)).isoformat(timespec='seconds')
    day_ago = (now - timedelta(days=1)).isoformat(timespec='seconds')
    recent = db.execute('SELECT COUNT(*) FROM bugReports WHERE visitorHash = ? AND dateFound > ?', (visitor, hour_ago)).fetchone()[0]
    today = db.execute('SELECT COUNT(*) FROM bugReports WHERE dateFound > ?', (day_ago,)).fetchone()[0]
    if recent >= BUG_REPORT_PER_VISITOR_PER_HOUR or today >= BUG_REPORT_GLOBAL_PER_DAY:
        return json_response(start_response, '429 Too Many Requests', {
            'ok': False, 'errors': {'form': 'Thank you -- that is a lot of reports. Please try again in an hour.'}})

    cursor = db.execute('''
        INSERT INTO bugReports (dateFound, title, bugOrFeature, severity, component, description,
            stepsToReproduce, expectedBehaviour, actualBehaviour, foundBy, server, phase,
            userAgent, viewport, visitorHash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Alpha', ?, ?, ?)
    ''', (now.isoformat(timespec='seconds'), clean['title'], clean['bugOrFeature'], clean['severity'],
          clean['component'], clean['description'], clean['stepsToReproduce'], clean['expectedBehaviour'],
          clean['actualBehaviour'], clean['foundBy'], SERVER_ROLE, clean['userAgent'], clean['viewport'], visitor))
    db.commit()
    return json_response(start_response, '201 Created', {'ok': True, 'id': cursor.lastrowid})


def application(environ, start_response):
    try:
        return route(environ, start_response)
    finally:
        if RELEASE_AFTER_REQUEST:
            release_site_dbs()   # Windows: let publishSite.py replace the files


def route(environ, start_response):
    path_info = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')
    query_params = parse_qs(environ.get('QUERY_STRING', ''))

    if method == 'POST' and path_info == '/api/visit':
        # One small POST per browser session; counted by city, no address kept (scripts/visitCounter.py).
        visitCounter.countVisit(environ)
        start_response('204 No Content', [])
        return []

    if method == 'POST' and path_info == '/api/bug-report':
        return handle_bug_report(environ, start_response)

    if method == 'GET' and path_info == '/api/news':
        return handle_news(query_params, start_response)
    if method == 'GET' and path_info == '/api/sky/object':
        return handle_sky_object(query_params, start_response)
    if method == 'GET' and path_info == '/api/sky/satellites':
        return handle_sky_satellites(environ, start_response)
    if method == 'GET' and path_info == '/api/sky/catalogue':
        return handle_sky_catalogue(environ, start_response)
    if method == 'GET' and path_info == '/api/usage':
        return handle_usage(start_response)
    if method == 'GET' and path_info == '/api/weather/sun-times':
        return handle_sun_times(start_response)
    if method == 'GET' and path_info == '/api/weather/now':
        return handle_weather_now(environ, start_response)
    if method == 'GET' and path_info == '/api/weather/series':
        return handle_weather_series(environ, query_params, start_response)
    if method == 'GET' and path_info == '/api/weather/events':
        return handle_weather_events(environ, query_params, start_response)
    if method == 'GET' and path_info == '/api/weather/aurora-at':
        return handle_weather_aurora_at(query_params, start_response)
    if method == 'GET' and path_info == '/api/weather/map':
        return handle_weather_map(environ, query_params, start_response)
    if method == 'GET' and path_info == '/api/weather/tec-latest':
        return handle_weather_tec_latest(environ, query_params, start_response)
    if method == 'GET' and path_info == '/api/weather/tec-code':
        return handle_weather_tec_code(environ, query_params, start_response)
    if method == 'GET' and path_info == '/api/weather/tec-index':
        return handle_weather_tec_index(environ, start_response)
    if method == 'GET' and path_info == '/api/weather/tec-at':
        return handle_weather_tec_at(query_params, start_response)
    if method == 'GET' and path_info == '/api/weather/tec-series':
        return handle_weather_tec_series(environ, query_params, start_response)
    if method == 'GET' and path_info == '/api/weather/tec-summary':
        return handle_weather_tec_summary(start_response)
    if method == 'GET' and path_info == '/api/status':
        return handle_status(start_response)
    if method == 'GET' and path_info == '/api/on-orbit/nationality':
        return handle_on_orbit_nationality(query_params, start_response)
    if method == 'GET' and path_info == '/api/on-orbit/regimes':
        return handle_on_orbit_regimes(query_params, start_response)
    if method == 'GET' and path_info == '/api/on-orbit/inclination':
        return handle_on_orbit_inclination(query_params, start_response)
    if method == 'GET' and path_info == '/api/on-orbit/sector':
        return handle_on_orbit_sector(query_params, start_response)
    if method == 'GET' and path_info == '/api/on-orbit/chart':
        return handle_on_orbit_chart(query_params, start_response)
    if method == 'GET' and path_info == '/api/on-orbit/owners':
        return handle_on_orbit_owners(query_params, start_response)
    if method == 'GET' and path_info == '/api/launches/per-year':
        return handle_launches_per_year(query_params, start_response)
    if method == 'GET' and path_info == '/api/launches/payloads-launched':
        return handle_launches_payloads_launched(query_params, start_response)
    if method == 'GET' and path_info == '/api/launches/by-country':
        return handle_launches_by_country(query_params, start_response)
    if method == 'GET' and path_info == '/api/launches/reentries':
        return handle_launches_reentries(query_params, start_response)
    if method == 'GET' and path_info == '/api/news/topic-counts':
        return handle_news_topic_counts(start_response)
    if method == 'GET' and path_info == '/api/ground-segment-assets':
        return handle_ground_segment_assets(start_response)
    if method == 'GET' and path_info == '/api/orbital-objects':
        return handle_orbital_objects(query_params, start_response)
    if method == 'GET' and path_info == '/api/orbital-objects/active':
        return handle_active_orbital_objects(start_response)
    if method == 'GET' and path_info == '/api/orbital-objects/active-nonpayload':
        return handle_active_nonpayload_objects(start_response)
    if method == 'GET' and path_info == '/api/orbital-objects/filter-options':
        return handle_filter_options(start_response)
    if method == 'GET' and path_info == '/api/orbital-objects/search':
        return handle_orbital_objects_search(query_params, start_response)

    return handle_static(path_info, start_response)


if __name__ == '__main__':
    SERVER_ROLE = 'DEV'
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer, make_server

    # One thread per connection. The plain WSGIServer serves one connection
    # at a time, so a browser holding an idle connection open (they open
    # spare ones in advance) left every other browser's page loading
    # forever. Local development only -- the live site runs under Passenger.
    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    with make_server('', PORT, application, server_class=ThreadingWSGIServer) as httpd:
        print(f'LCARS-FAS system online at http://localhost:{PORT}')
        httpd.serve_forever()
