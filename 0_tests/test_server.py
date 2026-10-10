"""Pre-deployment smoke and unit tests for server.py.

Pytest-based. Requires pytest (see requirements-dev.txt) -- the only
dev-only dependency in this repo; server.py itself remains stdlib-only
for the constrained GoDaddy host. Calls the WSGI `application` callable
directly (no socket, no running server needed) against the REAL local
databases in ingestionDBs/ (no mocks).

Run with:  pytest 0_tests/ -v
"""

import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402


def call_app(path, query_string=''):
    """Builds a minimal WSGI environ and invokes server.application()
    directly, returning (status, headers_dict, body_bytes)."""
    environ = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': path,
        'QUERY_STRING': query_string,
        'wsgi.input': io.BytesIO(b''),
        'wsgi.errors': sys.stderr,
    }
    captured = {}

    def start_response(status, headers):
        captured['status'] = status
        captured['headers'] = dict(headers)

    body = b''.join(server.application(environ, start_response))
    return captured['status'], captured['headers'], body


# --- API endpoint smoke tests ------------------------------------------
# Does every API endpoint respond with the right status/content-type and
# parseable JSON? This is the pre-deployment gate: if one of these fails,
# don't deploy.

def test_news_endpoint_returns_json_list():
    status, headers, body = call_app('/api/news')
    assert status == '200 OK'
    assert headers['Content-Type'] == 'application/json'
    assert isinstance(json.loads(body), list)


def test_news_endpoint_respects_limit_param():
    status, headers, body = call_app('/api/news', 'limit=3')
    assert status == '200 OK'
    assert len(json.loads(body)) <= 3


def test_news_endpoint_topic_filter_returns_json_list():
    status, headers, body = call_app('/api/news', 'topic=launch&limit=5')
    assert status == '200 OK'
    assert len(json.loads(body)) <= 5


def test_news_endpoint_unknown_topic_returns_empty_list():
    status, headers, body = call_app('/api/news', 'topic=noSuchTopic')
    assert status == '200 OK'
    assert json.loads(body) == []


def test_news_endpoint_topic_is_sql_injection_safe():
    status, headers, body = call_app('/api/news', "topic=%27%29%3B+DROP+TABLE+articles%3B--")
    assert status == '200 OK'
    assert json.loads(body) == []


def test_news_topic_counts_endpoint_shape():
    status, headers, body = call_app('/api/news/topic-counts')
    assert status == '200 OK'
    data = json.loads(body)
    assert isinstance(data['counts'], dict)
    assert 'updatedAt' in data


def test_status_endpoint_shape():
    status, headers, body = call_app('/api/status')
    assert status == '200 OK'
    data = json.loads(body)
    assert [row['data'] for row in data['sources']][:2] == ['News', 'Orbital elements']
    for row in data['sources']:
        assert set(row) >= {'data', 'source', 'lastRefreshUtc', 'changes', 'lastRunFailed', 'nextSyncUtc'}


def test_status_next_sync_is_last_start_plus_interval():
    import sqlite3
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE ingestionRuns (id INTEGER PRIMARY KEY, job TEXT, startedAt TEXT, '
                 'finishedAt TEXT, succeeded INTEGER, changes INTEGER, note TEXT)')
    conn.execute("INSERT INTO ingestionRuns (job, startedAt, finishedAt, succeeded, changes) "
                 "VALUES ('news', '2026-10-09T12:00:00Z', '2026-10-09T12:01:00Z', 1, 7)")
    conn.execute("INSERT INTO ingestionRuns (job, startedAt, finishedAt, succeeded, changes) "
                 "VALUES ('news', '2026-10-09T12:30:00Z', '2026-10-09T12:31:00Z', 0, NULL)")
    original = server.db
    server.db = conn
    try:
        row = server.status_row(server.STATUS_SOURCES[0])
    finally:
        server.db = original
    assert row['nextSyncUtc'] == '2026-10-09T13:00:00Z'     # latest attempt + 30 min
    assert row['lastRefreshUtc'] == '2026-10-09T12:01:00Z'  # latest *successful* run
    assert row['changes'] == 7
    assert row['lastRunFailed'] is True


def test_on_orbit_nationality_endpoint_shape():
    status, headers, body = call_app('/api/on-orbit/nationality')
    assert status == '200 OK'
    data = json.loads(body)
    assert isinstance(data['rows'], list)
    assert data['totalPayloads'] == sum(row['payloads'] for row in data['rows'])


def test_on_orbit_regimes_endpoint_shape():
    status, headers, body = call_app('/api/on-orbit/regimes')
    assert status == '200 OK'
    data = json.loads(body)
    assert (data['status'], data['kind']) == ('active', 'satellites')   # defaults
    for row in data['rows']:
        assert set(row) == {'regime', 'all', 'exclSpacex'}
        assert row['exclSpacex'] <= row['all']


def test_on_orbit_inclination_endpoint_shape():
    status, headers, body = call_app('/api/on-orbit/inclination', 'status=all&kind=spacecraft')
    assert status == '200 OK'
    data = json.loads(body)
    assert (data['status'], data['kind']) == ('all', 'spacecraft')
    assert isinstance(data['noInclination'], int)
    for bucket in data['buckets']:
        assert set(bucket) == {'from', 'to', 'payloads'}
        assert bucket['to'] - bucket['from'] == 5


def test_on_orbit_spacex_filter_reaches_every_chart_endpoint():
    for path in ('/api/on-orbit/nationality', '/api/on-orbit/inclination', '/api/on-orbit/sector',
                 '/api/on-orbit/owners'):
        status, headers, body = call_app(path, 'spacex=without')
        assert json.loads(body)['spacex'] == 'without'
        status, headers, body = call_app(path, 'spacex=bogus')
        assert json.loads(body)['spacex'] == 'with'     # unknown value falls back to the default


def test_launches_per_year_endpoint_shape():
    status, headers, body = call_app('/api/launches/per-year')
    assert status == '200 OK'
    data = json.loads(body)
    years = [row['year'] for row in data['rows']]
    assert years == sorted(years)
    for row in data['rows']:
        assert set(row) == {'year', 'launches', 'payloads', 'failures'}
        assert 0 <= row['failures'] <= row['launches'] <= row['payloads']


@pytest.mark.parametrize('path, field', [
    ('/api/launches/payloads-launched', 'payloads'),
    ('/api/launches/reentries', 'objects'),
])
def test_launch_history_endpoints_shape(path, field):
    status, headers, body = call_app(path)
    assert status == '200 OK'
    for row in json.loads(body)['rows']:
        assert isinstance(row['year'], int) and row[field] >= 0


@pytest.mark.parametrize('path', ['/api/launches/per-year', '/api/launches/by-country'])
def test_launch_log_charts_take_the_outcome_filter(path):
    every = json.loads(call_app(path, 'outcome=all')[2])
    success = json.loads(call_app(path, 'outcome=success')[2])
    assert (every['outcome'], success['outcome']) == ('all', 'success')
    assert json.loads(call_app(path, 'outcome=nonsense')[2])['outcome'] == 'all'
    assert sum(r['launches'] for r in success['rows']) <= sum(r['launches'] for r in every['rows'])
    if path.endswith('per-year'):
        assert all(r['failures'] == 0 for r in success['rows'])


@pytest.mark.parametrize('name', ['inclination-by-regime', 'altitude', 'altitude-vs-inclination', 'geo-belt',
                                  'active-by-regime', 'age', 'mission', 'sector-by-country', 'manufacturers',
                                  'buses', 'payloads-by-year', 'catalogue-by-type', 'debris-altitude',
                                  'debris-inclination', 'rocket-bodies-country', 'rocket-bodies-vehicle',
                                  'debris-origin', 'band', 'band-by-mission', 'band-by-regime', 'country-owner',
                                  'debris-history'])
def test_on_orbit_group_charts_answer(name):
    status, headers, body = call_app('/api/on-orbit/chart', f'name={name}&status=all&kind=objects&spacex=without')
    assert status == '200 OK'
    data = json.loads(body)
    assert (data['name'], data['kind'], data['spacex']) == (name, 'objects', 'without')
    assert isinstance(data['rows'], list) and isinstance(data['total'], int)


def test_on_orbit_unknown_chart_is_404():
    status, headers, body = call_app('/api/on-orbit/chart', "name=x%27%3B+DROP+TABLE+onOrbitObjects%3B--")
    assert status == '404 Not Found'


def test_launches_by_country_groups_and_matches_the_yearly_total():
    status, headers, body = call_app('/api/launches/by-country')
    assert status == '200 OK'
    rows = json.loads(body)['rows']
    assert {row['country'] for row in rows} <= set(server.LAUNCH_COUNTRY_SERIES)
    perYear = {row['year']: row['launches'] for row in json.loads(call_app('/api/launches/per-year')[2])['rows']}
    byCountry = {}
    for row in rows:
        byCountry[str(row['year'])] = byCountry.get(str(row['year']), 0) + row['launches']
    assert byCountry == perYear     # every launch in exactly one country


@pytest.mark.parametrize('path', ['/api/launches/per-year', '/api/launches/payloads-launched',
                                  '/api/launches/by-country', '/api/launches/reentries'])
def test_launch_charts_take_the_spacex_filter(path):
    status, headers, body = call_app(path, 'spacex=without')
    assert json.loads(body)['spacex'] == 'without'
    status, headers, body = call_app(path, 'spacex=bogus')
    assert json.loads(body)['spacex'] == 'with'     # unknown value falls back to the default


def test_on_orbit_filters_are_honoured_and_bad_values_fall_back():
    status, headers, body = call_app('/api/on-orbit/nationality', 'status=all&kind=spacecraft')
    assert (json.loads(body)['status'], json.loads(body)['kind']) == ('all', 'spacecraft')
    status, headers, body = call_app('/api/on-orbit/regimes', "status=%27%3B+DROP+TABLE+x%3B--&kind=nope")
    assert status == '200 OK'
    assert (json.loads(body)['status'], json.loads(body)['kind']) == ('active', 'satellites')


def test_ground_segment_assets_endpoint_returns_json_list():
    status, headers, body = call_app('/api/ground-segment-assets')
    assert status == '200 OK'
    assert headers['Content-Type'] == 'application/json'
    assert isinstance(json.loads(body), list)


def test_orbital_objects_endpoint_empty_ids_returns_empty_list():
    status, headers, body = call_app('/api/orbital-objects')
    assert status == '200 OK'
    assert json.loads(body) == []


def test_orbital_objects_endpoint_with_id_param():
    status, headers, body = call_app('/api/orbital-objects', 'ids=25544')
    assert status == '200 OK'
    assert isinstance(json.loads(body), list)


def test_orbital_objects_endpoint_ignores_malformed_ids():
    status, headers, body = call_app('/api/orbital-objects', 'ids=abc,,25544')
    assert status == '200 OK'
    json.loads(body)  # must not raise


def test_filter_options_endpoint_shape():
    status, headers, body = call_app('/api/orbital-objects/filter-options')
    assert status == '200 OK'
    data = json.loads(body)
    assert 'owners' in data
    assert 'groups' in data
    assert isinstance(data['owners'], list)
    assert isinstance(data['groups'], list)


def test_orbital_objects_search_default_shape():
    status, headers, body = call_app('/api/orbital-objects/search')
    assert status == '200 OK'
    data = json.loads(body)
    assert 'objects' in data
    assert 'truncated' in data
    assert isinstance(data['objects'], list)


@pytest.mark.parametrize('regime', ['LEO', 'MEO', 'GEO', 'OTHER'])
def test_orbital_objects_search_altitude_regime_filter_does_not_error(regime):
    status, headers, body = call_app(
        '/api/orbital-objects/search', f'altitudeRegime={regime}'
    )
    assert status == '200 OK'
    json.loads(body)


@pytest.mark.parametrize('band', ['EQUATORIAL', 'MID', 'POLAR_SSO'])
def test_orbital_objects_search_inclination_band_filter_does_not_error(band):
    status, headers, body = call_app(
        '/api/orbital-objects/search', f'inclinationBand={band}'
    )
    assert status == '200 OK'
    json.loads(body)


def test_orbital_objects_search_name_filter_is_sql_injection_safe():
    # Parameterised query check: a classic injection payload must be
    # treated as a literal search string, not break the query.
    status, headers, body = call_app(
        '/api/orbital-objects/search', "name=%27%3B+DROP+TABLE+orbital_objects%3B--"
    )
    assert status == '200 OK'
    json.loads(body)


# --- Static file serving -------------------------------------------------
# Regression coverage for the exact failure mode that already bit this
# project once in production: a deploy silently served a stub page
# instead of the real frontend, and it *looked* fine at a glance -- only
# the Content-Type gave it away. These tests check that.

def test_root_serves_index_html():
    status, headers, body = call_app('/')
    assert status == '200 OK'
    assert headers['Content-Type'] == 'text/html'
    assert b'LCARS' in body


def test_js_asset_has_correct_content_type():
    status, headers, body = call_app('/assets/lcars.js')
    assert status == '200 OK'
    assert headers['Content-Type'] == 'text/javascript'


def test_css_asset_has_correct_content_type():
    status, headers, body = call_app('/assets/classic.css')
    assert status == '200 OK'
    assert headers['Content-Type'] == 'text/css'


def test_missing_file_returns_404():
    status, headers, body = call_app('/assets/does-not-exist-at-all.js')
    assert status == '404 Not Found'


# Only index.html and assets/ are served (bug 7): server code, scripts,
# databases and credentials must never come back as files, however the path
# is dressed up.

def test_index_html_by_name_is_served():
    status, headers, body = call_app('/index.html')
    assert status == '200 OK'
    assert b'LCARS' in body


def test_nested_asset_is_served():
    status, headers, body = call_app('/assets/leaflet/leaflet.js')
    assert status == '200 OK'


@pytest.mark.parametrize('path', [
    '/server.py',
    '/setupCron.sh',
    '/deployToGoDaddy.sh',
    '/spacetrack.env.example',
    '/scripts/readNews.py',
    '/ingestionDBs/groundSegmentAssets.db',
    '/.gitignore',
    '/bugsDB.xlsx',
    '/assets/../server.py',
    '/assets/../../server.py',
    '/assets/leaflet/../../server.py',
    r'/assets/..\server.py',   # Windows separator
    '/assets/../ingestionDBs/groundSegmentAssets.db',
    '/assets\x00.js',
])
def test_files_outside_index_and_assets_are_not_served(path):
    status, headers, body = call_app(path)
    assert status == '404 Not Found'
    assert body == b'404 Not Found'


# --- Pure logic unit tests ------------------------------------------------
# Fast, no-DB unit tests for standalone functions.

def test_get_param_returns_first_value():
    assert server.get_param({'x': ['a', 'b']}, 'x') == 'a'


def test_get_param_returns_none_when_absent():
    assert server.get_param({}, 'missing') is None
