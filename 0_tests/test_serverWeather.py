"""Tests for the /api/weather/{now,series,events,map} endpoints and the
weather rows of the freshness table: a temporary siteWeather.db built by
publishSite from temporary ingestion databases. No real database is read."""

import gzip
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import dbPaths  # noqa: E402
import publishSite as ps  # noqa: E402
import server  # noqa: E402
import spaceWeatherSamples as sws  # noqa: E402


def call(path, query='', headers=None):
    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'QUERY_STRING': query, 'wsgi.input': io.BytesIO(b''),
               'wsgi.errors': sys.stderr, **(headers or {})}
    seen = {}

    def start(status, hdrs):
        seen['status'], seen['headers'] = status, dict(hdrs)

    body = b''.join(server.application(environ, start))
    return seen['status'], seen['headers'], body


@pytest.fixture
def weather(tmp_path, monkeypatch):
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(dbPaths, 'LEGACY', False)
    server.release_site_dbs()
    server._weather_caches.clear()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    stamp = lambda **kw: (now - timedelta(**kw)).strftime('%Y-%m-%dT%H:%M:%SZ')   # noqa: E731
    db = sws.connect(dbPaths.dbPath(dbPaths.SWPC_DB))
    rows = [('l1WindSpeed', stamp(minutes=i), 400.0 + i, 'km/s', 'SOLAR1') for i in range(300)]
    rows += [('l1WindSpeed', stamp(days=10, minutes=i), 500.0, 'km/s', 'SOLAR1') for i in range(120)]
    rows += [('swpcForecastAp', stamp(days=-1), 18.0, 'ap', 'issued'), ('swpcKp', stamp(hours=1), 2.0, 'Kp', 'observed')]
    sws.upsertSamples(db, rows)
    sws.upsertEvents(db, [('flare', stamp(days=1), 'f1', {'class': 'M1'})])
    sws.upsertMap(db, 'testMap', stamp(minutes=5), {'grid': [1, 2]})
    db.close()
    ps.publish('weather', now)
    yield
    server.release_site_dbs()


def test_now_gives_the_newest_past_reading_of_each_series(weather):
    status, headers, body = call('/api/weather/now')
    data = json.loads(body)
    assert status == '200 OK' and headers['Content-Type'] == 'application/json'
    assert data['latest']['l1WindSpeed'][1] == 400.0
    assert 'swpcForecastAp' not in data['latest']    # a future-dated forecast is not "now"
    assert data['latest']['swpcKp'][1] == 2.0 and data['maps'] == ['testMap']


def test_series_native_and_hourly(weather):
    data = json.loads(call('/api/weather/series', 'name=l1WindSpeed&range=6h')[2])
    assert data['resolution'] == 'native' and data['unit'] == 'km/s' and len(data['t']) == len(data['v']) == 300
    assert data['t'] == sorted(data['t'])
    wide = json.loads(call('/api/weather/series', 'name=l1WindSpeed&range=30d')[2])
    assert wide['resolution'] == 'hourly' and 0 < len(wide['t']) < 300


def test_series_gives_the_quality_text_only_when_asked_and_has_a_25_year_range(weather):
    plain = json.loads(call('/api/weather/series', 'name=l1WindSpeed&range=6h')[2])
    assert 'q' not in plain
    asked = json.loads(call('/api/weather/series', 'name=l1WindSpeed&range=6h&quality=1')[2])
    assert len(asked['q']) == len(asked['t']) and set(asked['q']) == {'SOLAR1'}
    assert asked['v'] == plain['v']
    assert call('/api/weather/series', 'name=l1WindSpeed&range=25y')[0].startswith('200')


def test_series_can_be_rounded_to_significant_figures(weather):
    exact = json.loads(call('/api/weather/series', 'name=l1WindSpeed&range=6h')[2])['v']
    rounded = json.loads(call('/api/weather/series', 'name=l1WindSpeed&range=6h&sig=2')[2])['v']
    assert rounded[0] == float(f'{exact[0]:.1e}') and rounded != exact
    assert json.loads(call('/api/weather/series', 'name=l1WindSpeed&range=6h&sig=x')[2])['v'] == exact   # junk: ignored


def test_series_rejects_bad_input_and_unknown_names(weather):
    assert call('/api/weather/series', 'name=l1WindSpeed&range=5y')[0].startswith('400')
    assert call('/api/weather/series', "name=x'%3B--&range=24h")[0].startswith('400')
    assert call('/api/weather/series', 'range=24h')[0].startswith('400')
    assert call('/api/weather/series', 'name=noSuchSeries&range=24h')[0].startswith('404')


def test_events_and_maps(weather):
    data = json.loads(call('/api/weather/events', 'type=flare&days=7')[2])
    assert data['events'][0]['id'] == 'f1' and data['events'][0]['record'] == {'class': 'M1'}
    assert json.loads(call('/api/weather/events', 'type=CME')[2])['events'] == []
    assert call('/api/weather/events', 'type=a%20b')[0].startswith('400')
    assert json.loads(call('/api/weather/map', 'name=testMap')[2])['map'] == {'grid': [1, 2]}
    assert call('/api/weather/map', 'name=nothing')[0].startswith('404')


def test_aurora_at_looks_up_any_place_in_the_stored_maps(weather, tmp_path):
    ovation = {'obs': 'O', 'forecast': 'F', 'latMin': -90, 'lonMin': 0, 'step': 1,
               'rows': [[0] * 360 for _ in range(181)]}
    ovation['rows'][64 + 90][338] = 42      # 64 N, 22 W
    ovation['rows'][-53 + 90][100] = 21     # 53 S, 100 E
    drap = {'valid': 'V', 'lonMin': -178, 'lonStep': 4, 'latMax': 89, 'latStep': -2,
            'tenths': [[0] * 90 for _ in range(90)]}
    drap['tenths'][(89 - 65) // 2][39] = 55   # 65 N, 22 W
    db = sws.connect(dbPaths.dbPath(dbPaths.SWPC_DB))
    sws.upsertMap(db, 'ovation', '2026-10-24T16:25:00Z', ovation)
    sws.upsertMap(db, 'drapGlobal', '2026-10-24T16:30:00Z', drap)
    db.close()
    ps.publish('weather')
    north = json.loads(call('/api/weather/aurora-at', 'lat=64&lon=-22')[2])
    assert north['aurora'] == {'index': 42, 'cellLat': 64, 'cellLon': -22, 'observedUtc': 'O', 'forecastUtc': 'F'}
    assert north['absorption'] == {'mhz': 5.5, 'validUtc': 'V'}
    assert json.loads(call('/api/weather/aurora-at', 'lat=65&lon=-22')[2])['absorption']['mhz'] == 5.5
    assert json.loads(call('/api/weather/aurora-at', 'lat=-52.6&lon=100.2')[2])['aurora']['index'] == 21
    assert json.loads(call('/api/weather/aurora-at', 'lat=64&lon=338')[2])['aurora']['index'] == 42   # 0 to 360 east works too
    assert json.loads(call('/api/weather/aurora-at', 'lat=90&lon=180')[2])['aurora']['cellLat'] == 90


@pytest.mark.parametrize('query', ['', 'lat=10', 'lon=10', 'lat=91&lon=0', 'lat=-91&lon=0', 'lat=0&lon=361',
                                   'lat=0&lon=-181', 'lat=abc&lon=0', 'lat=nan&lon=0', 'lat=0&lon=inf', 'lat=1e999&lon=0'])
def test_aurora_at_refuses_bad_input(weather, query):
    assert call('/api/weather/aurora-at', query)[0].startswith('400')


def test_aurora_at_without_a_map_or_a_file(weather, tmp_path, monkeypatch):
    assert call('/api/weather/aurora-at', 'lat=0&lon=0')[0].startswith('404')   # the fixture holds no OVATION map
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path / 'empty'))
    os.makedirs(str(tmp_path / 'empty'))
    server.release_site_dbs()
    assert call('/api/weather/aurora-at', 'lat=0&lon=0')[0].startswith('503')


def test_thirteen_months_of_daily_f107_with_the_81_day_mean(weather):
    """400 days of daily F10.7 survive the publish and come out of /api/weather/series?range=400d; the centred
    81-day mean of the observed flux exists only where the whole window does (days 41 to 360 of 400)."""
    from datetime import date
    today = date.today()
    gfz = sws.connect(dbPaths.dbPath(dbPaths.GFZ_DB))
    days = [(today - timedelta(days=d)).strftime('%Y-%m-%dT00:00:00Z') for d in range(399, -1, -1)]
    sws.upsertSamples(gfz, [('gfzF107Obs', t, 100.0 + i % 7, 'sfu', None) for i, t in enumerate(days)]
                      + [('gfzF107Adj', t, 99.0 + i % 7, 'sfu', None) for i, t in enumerate(days)])
    gfz.close()
    ps.publish('weather')
    for name in ('gfzF107Obs', 'gfzF107Adj'):
        data = json.loads(call('/api/weather/series', f'name={name}&range=400d')[2])
        assert data['range'] == '400d' and data['resolution'] == 'native' and len(data['t']) == len(data['v']) >= 399
        assert data['t'][0] <= days[1] and data['unit'] == 'sfu'
    mean = json.loads(call('/api/weather/series', 'name=derivedF107A81&range=400d')[2])
    assert len(mean['t']) == 400 - 80        # centred, full windows only: nothing for the first 40 days or the last 40
    assert mean['t'][0] == days[40] and mean['t'][-1] == days[399 - 40]
    db = sqlite3.connect(dbPaths.dbPath(dbPaths.SITE_WEATHER_DB))
    qualities = {r[0] for r in db.execute("SELECT quality FROM samples WHERE series = 'derivedF107A81'")}
    assert qualities == {'centred 81-day mean of the cleaned observed flux'}


def test_cosmic_ray_and_sunspot_series_are_published_and_the_whole_monthly_record_is_served(weather):
    import ingestionGCR
    import ingestionSILSO
    fixtures = os.path.join(ROOT, '0_tests', 'fixtures')
    read = lambda name: open(os.path.join(fixtures, name), encoding='utf-8').read()   # noqa: E731
    gcr = ingestionGCR.openDb(dbPaths.dbPath(dbPaths.GCR_DB))
    sws.upsertSamples(gcr, ingestionGCR.parseCounts(read('nmdbOuluMonthly1964.csv'), 'OULU', ingestionGCR.MONTHLY))
    sws.upsertSamples(gcr, ingestionGCR.parseCounts(read('nmdbOuluHourly30d.csv'), 'OULU', ingestionGCR.HOURLY))
    from ingestionLog import recordRun
    recordRun(gcr, 'gcr', '2026-10-24T19:45:00Z', True, 5, 'test')
    gcr.close()
    sil = ingestionSILSO.openDb(dbPaths.dbPath(dbPaths.SILSO_DB))
    sws.upsertSamples(sil, ingestionSILSO.parseMonthly(read('silsoMonthly.csv')))
    sil.close()
    ps.publish('weather')
    sun = json.loads(call('/api/weather/series', 'name=silsoMonthlyMean&range=all')[2])
    assert len(sun['t']) == 3333 and sun['t'][0] == '1749-01-01T00:00:00Z' and sun['v'][-1] == 60.3
    monthly = json.loads(call('/api/weather/series', 'name=gcrOuluMonthlyCorrected&range=all')[2])
    assert len(monthly['t']) == 750 and monthly['unit'] == 'cts/min'
    assert call('/api/weather/series', 'name=silsoMonthlyMean&range=400d')[0].startswith('200')
    now = json.loads(call('/api/weather/now')[2])['latest']
    assert 'gcrOuluCorrected' not in now or now['gcrOuluCorrected'][3] in ('verified', 'provisional')
    runs = sqlite3.connect(dbPaths.dbPath(dbPaths.SITE_WEATHER_DB)).execute('SELECT DISTINCT sourceDb FROM ingestionRuns').fetchall()
    assert ('ingestionGCR',) in runs


def test_gzip_etag_and_304(weather):
    status, headers, body = call('/api/weather/series', 'name=l1WindSpeed&range=6h', {'HTTP_ACCEPT_ENCODING': 'gzip'})
    assert headers['Content-Encoding'] == 'gzip' and json.loads(gzip.decompress(body))['name'] == 'l1WindSpeed'
    assert 'max-age' in headers['Cache-Control']
    again = call('/api/weather/series', 'name=l1WindSpeed&range=6h',
                 {'HTTP_ACCEPT_ENCODING': 'gzip', 'HTTP_IF_NONE_MATCH': headers['ETag']})
    assert again[0].startswith('304') and again[2] == b''


def test_without_a_weather_file_the_endpoints_say_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(dbPaths, 'LEGACY', False)
    server.release_site_dbs()
    server._weather_caches.clear()
    for path, query in (('/api/weather/now', ''), ('/api/weather/series', 'name=a&range=24h'),
                        ('/api/weather/map', 'name=a')):
        assert call(path, query)[0].startswith('503')
    assert call('/api/weather/events', 'type=CME')[0].startswith('503')


def test_status_has_weather_rows_with_runs_from_the_weather_file(weather):
    names = [s['data'] for s in server.STATUS_SOURCES]
    assert {'Space weather', 'Geomagnetic indices', 'Solar events'} <= set(names)
    row = server.status_row(next(s for s in server.STATUS_SOURCES if s['data'] == 'Space weather'))
    assert row['lastRefreshUtc'] is None and row['lastRunFailed'] is False   # no swpcFast run recorded in this fixture
