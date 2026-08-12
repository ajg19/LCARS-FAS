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


# --- Pure logic unit tests ------------------------------------------------
# Fast, no-DB unit tests for standalone functions.

def test_parse_inclination_deg_valid_tle_line():
    line2 = '2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49560328 12345'
    assert server.parse_inclination_deg(line2) == pytest.approx(51.6416, abs=1e-3)


@pytest.mark.parametrize('bad_input', ['not a tle line', None, ''])
def test_parse_inclination_deg_handles_bad_input(bad_input):
    assert server.parse_inclination_deg(bad_input) is None


def test_get_param_returns_first_value():
    assert server.get_param({'x': ['a', 'b']}, 'x') == 'a'


def test_get_param_returns_none_when_absent():
    assert server.get_param({}, 'missing') is None
