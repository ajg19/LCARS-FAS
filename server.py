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


# Serves frontend static assets. Maps "/" to index.html, otherwise looks
# for the requested file relative to this script's own directory. Content-
# type mapping only branches for .js/.css/.json, defaulting to text/html
# for anything else (including images/fonts) -- matches server.js exactly,
# quirk and all.
def handle_static(path_info, start_response):
    rel_path = 'index.html' if path_info == '/' else path_info.lstrip('/')
    file_path = os.path.join(BASE_DIR, rel_path)

    if not os.path.isfile(file_path):
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
