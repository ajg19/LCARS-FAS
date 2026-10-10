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

import json
import mimetypes
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

PORT = 3000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, 'ingestionDBs')


def open_db(filename, read_only=False):
    path = os.path.join(DB_DIR, filename)
    if read_only:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# Connect to the local space news SQLite database.
db = open_db('space_news.db')

# Ground segment assets DB (built by rschGrdSgmt/build_ground_segment_db.py)
# -- a separate file/connection, unrelated to the news database above.
ground_segment_db = open_db('groundSegmentAssets.db')

# Orbital objects (OMM elements) DB, populated/refreshed by the scripts/
# ingestion jobs (ingestOrbitalData.py, ingestSatcat.py, enrichEirp.py,
# ingestSatnogsRf.py -- separate processes) -- read-only here since this
# endpoint only ever reads it.
orbital_objects_db = open_db('orbitalObjects.db', read_only=True)


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
            rows = db.execute(
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
# `job` matches the name each ingestion script records in its database's
# ingestionRuns table (scripts/ingestionLog.py); `interval_min` must match
# that job's cron schedule (setupCron.sh / scripts/runPipeline.sh) -- the
# next sync is estimated as the last run's start plus this interval, which
# stays right whatever timezone the host's cron uses. `fallback_sql` gives a
# last-refresh time for a database with no recorded runs yet.
STATUS_SOURCES = [
    {'data': 'News', 'source': '18 RSS feeds', 'db': 'news', 'job': 'news', 'interval_min': 30,
     'fallback_sql': 'SELECT MAX(fetched_at) FROM articles'},
    # NORAD = the US satellite catalogue (now maintained by US Space Force);
    # CelesTrak and Space-Track distribute it, SatNOGS is independent.
    {'data': 'Orbital elements', 'source': 'NORAD via CelesTrak · Space-Track; SatNOGS', 'db': 'orbital',
     'job': 'orbitalElements', 'interval_min': 12 * 60,
     'fallback_sql': 'SELECT MAX(fetchedAt) FROM orbital_objects'},
    {'data': 'Satellite catalogue', 'source': 'NORAD SATCAT via CelesTrak · Space-Track', 'db': 'orbital',
     'job': 'satcat', 'interval_min': 24 * 60},
    {'data': 'Downlink EIRP', 'source': 'Filings · band plans', 'db': 'orbital', 'job': 'eirp',
     'interval_min': 12 * 60},
    {'data': 'Radio frequencies', 'source': 'SatNOGS DB', 'db': 'orbital', 'job': 'satnogsRf',
     'interval_min': 12 * 60},
    {'data': 'Launch & ownership', 'source': 'GCAT', 'db': 'gcat', 'job': 'gcat',
     'interval_min': 7 * 24 * 60},
]


def gcat_db():
    """gcat.db, opened read-only on first use -- or None while it doesn't
    exist yet (before scripts/ingestGcat.py's first run). Opened lazily,
    not at import like the other databases, so a missing file can't stop
    the whole server starting."""
    global _gcat_db
    if _gcat_db is None and os.path.exists(os.path.join(DB_DIR, 'gcat.db')):
        _gcat_db = open_db('gcat.db', read_only=True)
    return _gcat_db


_gcat_db = None


def stats_db():
    """onOrbitStats.db (scripts/orbitStats.py's precomputed ON-ORBIT figures),
    opened read-only on first use -- or None until it exists. Lazy for the
    same reason as gcat_db()."""
    global _stats_db
    if _stats_db is None and os.path.exists(os.path.join(DB_DIR, 'onOrbitStats.db')):
        _stats_db = open_db('onOrbitStats.db', read_only=True)
    return _stats_db


_stats_db = None


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


def latest_runs(conn, job):
    """(latest run, latest successful run) for `job`, each a sqlite3.Row or
    None -- (None, None) for a database with no ingestionRuns table yet."""
    try:
        latest = conn.execute(
            'SELECT startedAt, finishedAt, succeeded, changes FROM ingestionRuns '
            'WHERE job = ? ORDER BY id DESC LIMIT 1', (job,)).fetchone()
        latest_ok = conn.execute(
            'SELECT startedAt, finishedAt, succeeded, changes FROM ingestionRuns '
            'WHERE job = ? AND succeeded = 1 ORDER BY id DESC LIMIT 1', (job,)).fetchone()
    except sqlite3.OperationalError as e:
        if 'no such table' in str(e):
            return None, None
        raise
    return latest, latest_ok


def status_row(spec):
    row = {'data': spec['data'], 'source': spec['source'], 'lastRefreshUtc': None,
           'changes': None, 'lastRunFailed': False, 'nextSyncUtc': None}

    conn = {'news': db, 'orbital': orbital_objects_db, 'gcat': gcat_db()}[spec['db']]
    if conn is None:
        return row   # database not created yet -- nothing recorded
    latest, latest_ok = latest_runs(conn, spec['job'])
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
    tests left out), from gcat.db's launch log -- one row per payload, so
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
    request from gcat.db's launch log; W/O SPACEX leaves out SpaceX's."""
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
            rows = db.execute('SELECT topic, articleCount, updatedAt FROM newsTopicCounts').fetchall()
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
        rows = ground_segment_db.execute('SELECT * FROM ground_segment_assets').fetchall()
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
        rows = orbital_objects_db.execute(
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
        rows = orbital_objects_db.execute(
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
        rows = orbital_objects_db.execute(
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
        owners = [r['owner'] for r in orbital_objects_db.execute(
            'SELECT DISTINCT owner FROM orbital_objects WHERE owner IS NOT NULL ORDER BY owner'
        ).fetchall()]
        groups = [r['groupName'] for r in orbital_objects_db.execute(
            'SELECT DISTINCT groupName FROM orbital_object_groups ORDER BY groupName'
        ).fetchall()]
        launch_sites = [r['launchSite'] for r in orbital_objects_db.execute(
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
        rows = orbital_objects_db.execute(
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
# assets/. Anything else -- server.py, scripts/, ingestionDBs/, setupCron.sh,
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


def application(environ, start_response):
    path_info = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')
    query_params = parse_qs(environ.get('QUERY_STRING', ''))

    if method == 'GET' and path_info == '/api/news':
        return handle_news(query_params, start_response)
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
    from wsgiref.simple_server import make_server

    with make_server('', PORT, application) as httpd:
        print(f'LCARS-FAS system online at http://localhost:{PORT}')
        httpd.serve_forever()
