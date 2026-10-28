"""Tests for the /api/weather/tec-* endpoints (CODE and NOAA GloTEC total electron content) and for
the TEC part of the weather publish: a temporary ingestionTEC.db holding the recorded maps
(0_tests/fixtures), published into a temporary siteWeather.db. NOAA is never reached: the
on-demand GloTEC fetch is given a stand-in."""

import functools
import gzip
import io
import json
import math
import os
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import dbPaths  # noqa: E402
import ingestionTEC as tec  # noqa: E402
import publishSite as ps  # noqa: E402
import server  # noqa: E402
import spaceWeatherSamples as sws  # noqa: E402
from ingestionLog import recordRun  # noqa: E402


def fixture(name):
    with open(os.path.join(ROOT, '0_tests', 'fixtures', name), 'rb') as f:
        data = f.read()
    return (gzip.decompress(data) if name.endswith('.gz') else data).decode('utf-8')


RAPID, P0D, GLOTEC, LISTING = (fixture('codeGimRAP_2026296.INX.gz'), fixture('codeGimP0D_2026297.INX.gz'),
                               fixture('glotecMap_20261024T1835.json.gz'), fixture('glotecListing_20261024T2114.html'))


def call(path, query='', headers=None):
    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'QUERY_STRING': query, 'wsgi.input': io.BytesIO(b''),
               'wsgi.errors': sys.stderr, **(headers or {})}
    seen = {}

    def start(status, hdrs):
        seen['status'], seen['headers'] = status, dict(hdrs)

    body = b''.join(server.application(environ, start))
    return seen['status'], seen['headers'], body


def glotecAt(valid):
    data = json.loads(GLOTEC)
    data['time_tag'] = valid
    return json.dumps(data)


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


@functools.lru_cache(maxsize=None)
def parsedFirstMap(kind):
    return tec.parseIonex(RAPID if kind == 'observed' else P0D, 'rapid' if kind == 'observed' else 'pred1', kind,
                          'RAPID' if kind == 'observed' else '1-DAY PREDICTED')[0][2]


def codeMapAt(valid, kind, product, issued, offset=0):
    """A CODE map from the recorded file, given another valid time (and every value `offset` higher)."""
    record = parsedFirstMap(kind)
    record = dict(record, product=product, validUtc=valid, issuedUtc=issued, rows=[[None if v is None else v + offset for v in r] for r in record['rows']])
    return (issued, valid, record)


@pytest.fixture
def weather(tmp_path, monkeypatch):
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(dbPaths, 'LEGACY', False)
    monkeypatch.setattr(server, 'tec_fetch', None)
    server.release_site_dbs()
    server._weather_caches.clear()
    server._tec_latest.update(checkedAt=0.0, failedAt=0.0, validUtc=None, gz=None)
    swpc = sws.connect(dbPaths.dbPath(dbPaths.SWPC_DB))
    sws.upsertSamples(swpc, [('swpcKp', stamp(datetime.now(timezone.utc)), 2.0, 'Kp', 'observed')])
    swpc.close()
    yield tmp_path
    server.release_site_dbs()


def holdTec(now, glotecAges=(), codeHours=2):
    """Fills ingestionTEC.db: GloTEC maps `glotecAges` (hours old; each with TEC raised by its age, so they differ),
    CODE observed maps for the `codeHours` hours up to the one nearest now, a prediction for the next hours, and publishes."""
    db = tec.openDb(dbPaths.dbPath(dbPaths.TEC_DB))
    for age in glotecAges:
        valid = stamp(now - timedelta(hours=age))
        data = json.loads(glotecAt(valid))
        for feature in data['features']:
            feature['properties']['tec'] += age
        record, samples = tec.parseGlotec(json.dumps(data))
        tec.storeMaps(db, [(valid, valid, record)], samples)
    nearest = (now + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
    issued = stamp(nearest - timedelta(hours=10))
    maps = [codeMapAt(stamp(nearest - timedelta(hours=h)), 'observed', 'rapid', issued, offset=h) for h in range(codeHours)]
    maps += [codeMapAt(stamp(nearest + timedelta(hours=h)), 'prediction', 'pred1', issued, offset=100 + h) for h in range(1, 4)]
    tec.storeMaps(db, maps)
    recordRun(db, 'tecGlotec', stamp(now), True, 1, 'test')
    db.close()
    ps.publish('weather')


NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)


def test_publish_carries_the_maps_the_summary_series_and_the_runs(weather):
    holdTec(NOW, glotecAges=(1, 2))
    db = sqlite3.connect(dbPaths.dbPath(dbPaths.SITE_WEATHER_DB))
    assert db.execute("SELECT source, COUNT(*) FROM tecMaps GROUP BY source ORDER BY source").fetchall() == [('code', 5), ('glotec', 2)]
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'glotecTecMax'").fetchone()[0] == 2
    assert ('ingestionTEC', 'tecGlotec') in db.execute('SELECT sourceDb, job FROM ingestionRuns').fetchall()


def test_publish_without_a_tec_database_still_works(weather):
    ps.publish('weather')
    assert sqlite3.connect(dbPaths.dbPath(dbPaths.SITE_WEATHER_DB)).execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0] == 0


def test_the_freshness_table_has_the_two_ionosphere_rows(weather):
    names = {s['data']: s for s in server.STATUS_SOURCES}
    assert names['Ionosphere maps (CODE)']['jobs'] == ('tecCode',) and names['Ionosphere maps (CODE)']['interval_min'] == 1440
    assert names['Ionosphere maps (GloTEC)']['jobs'] == ('tecGlotec',) and names['Ionosphere maps (GloTEC)']['interval_min'] == 180


def test_index_lists_what_is_held(weather):
    holdTec(NOW, glotecAges=(1, 2))
    data = json.loads(call('/api/weather/tec-index')[2])
    assert len(data['glotec']) == 2 and data['glotec'] == sorted(data['glotec'])
    hours = [h for day in data['code']['observed'].values() for h in day]
    assert len(hours) == 2 and sum(len(day) for day in data['code']['prediction'].values()) == 3
    assert list(next(iter(data['code']['observed'].values())).values())[0][0] == 'rapid'


def test_a_code_map_is_served_whole_gzipped_or_not(weather):
    holdTec(NOW)
    nearest = (NOW + timedelta(minutes=30)).replace(minute=0)
    query = f'kind=observed&day={nearest:%Y-%m-%d}&hour={nearest.hour}'
    status, headers, body = call('/api/weather/tec-code', query, {'HTTP_ACCEPT_ENCODING': 'gzip'})
    record = json.loads(gzip.decompress(body))
    assert status == '200 OK' and headers['Content-Encoding'] == 'gzip' and record['product'] == 'rapid' and record['rows'][0][:3] == [68, 70, 71]
    assert len(body) < 12000
    plain = call('/api/weather/tec-code', query)
    assert 'Content-Encoding' not in plain[1] and json.loads(plain[2]) == record
    again = call('/api/weather/tec-code', query, {'HTTP_ACCEPT_ENCODING': 'gzip', 'HTTP_IF_NONE_MATCH': headers['ETag']})
    assert again[0].startswith('304') and again[2] == b''
    assert json.loads(call('/api/weather/tec-code', query + '&product=rapid')[2]) == record
    assert call('/api/weather/tec-code', query + '&product=pred2')[0].startswith('404')


def test_the_newest_issue_of_a_prediction_wins(weather):
    holdTec(NOW)
    nearest = (NOW + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    db = tec.openDb(dbPaths.dbPath(dbPaths.TEC_DB))
    tec.storeMaps(db, [codeMapAt(stamp(nearest), 'prediction', 'pred2', stamp(nearest - timedelta(hours=1)), offset=500)])
    db.close()
    ps.publish('weather')
    record = json.loads(call('/api/weather/tec-code', f'kind=prediction&day={nearest:%Y-%m-%d}&hour={nearest.hour}')[2])
    assert record['product'] == 'pred2' and record['rows'][0][0] == 584


@pytest.mark.parametrize('query', ['', 'kind=observed&day=2026-10-24', 'kind=observed&hour=3', 'kind=forecast&day=2026-10-24&hour=3',
                                   'kind=observed&day=2026-13-40&hour=3', 'kind=observed&day=yesterday&hour=3',
                                   'kind=observed&day=2026-10-24&hour=24', 'kind=observed&day=2026-10-24&hour=-1',
                                   'kind=observed&day=2026-10-24&hour=x', 'kind=observed&day=2026-10-24&hour=3&product=glotec',
                                   "kind=observed&day=2026-10-24&hour=3&product=x'%3B--"])
def test_tec_code_refuses_bad_input(weather, query):
    ps.publish('weather')
    assert call('/api/weather/tec-code', query)[0].startswith('400')


def test_tec_code_unknown_map_and_no_file(weather, tmp_path, monkeypatch):
    holdTec(NOW)
    assert call('/api/weather/tec-code', 'kind=observed&day=2020-01-01&hour=3')[0].startswith('404')
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path / 'empty'))
    os.makedirs(str(tmp_path / 'empty'))
    server.release_site_dbs()
    for path, query in (('/api/weather/tec-code', 'kind=observed&day=2020-01-01&hour=3'), ('/api/weather/tec-index', ''),
                        ('/api/weather/tec-series', 'lat=1&lon=1'), ('/api/weather/tec-at', 'lat=1&lon=1')):
        assert call(path, query)[0].startswith('503'), path


def test_tec_at_reads_the_nearest_cell_of_both_sources(weather):
    holdTec(NOW, glotecAges=(1,))
    data = json.loads(call('/api/weather/tec-at', 'lat=-21&lon=102')[2])
    glotec = data['glotec']
    assert (glotec['cellLat'], glotec['cellLon']) == (-21.25, 102.5)
    assert glotec['tec'] == 8.9 and glotec['anomaly'] == -1.2 and glotec['nmF2'] == 23 and glotec['hmF2'] == 337 and glotec['quality'] == 0
    assert glotec['foF2'] == round(0.898 * math.sqrt(23), 2) and 4.2 < glotec['foF2'] < 4.5
    code = data['code']
    assert code['kind'] == 'observed' and code['product'] == 'rapid' and (code['cellLat'], code['cellLon']) == (-20.0, 100.0)
    expected = tec.parseIonex(RAPID, 'rapid', 'observed', 'RAPID')[0][2]['rows'][43][56] / 10
    assert code['tec'] == expected and data['foF2Note'].startswith('indicative')
    assert data['lon'] == 102
    assert glotec['observed'] is False and glotec['anomalyReliable'] is False          # flag 0 in this cell
    assert data['anomalyUnit'] == 'TECU (inferred)' and 'model' in data['anomalyNote'] and 'coverage' in data['qualityMeaning']
    flagged = json.loads(call('/api/weather/tec-at', 'lat=40&lon=-100')[2])['glotec']       # the central US, flag 5 in the saved map
    assert flagged['quality'] > 0 and flagged['observed'] is True and flagged['anomalyReliable'] is True


def test_tec_at_wraps_the_date_line_and_takes_east_longitudes(weather):
    holdTec(NOW, glotecAges=(1,))
    west = json.loads(call('/api/weather/tec-at', 'lat=10&lon=-179.9')[2])
    east = json.loads(call('/api/weather/tec-at', 'lat=10&lon=180.1')[2])
    assert west['glotec']['cellLon'] == -177.5 and east['glotec']['cellLon'] == -177.5 and west['code']['cellLon'] == -180.0
    assert json.loads(call('/api/weather/tec-at', 'lat=10&lon=348')[2])['glotec']['cellLon'] == -12.5
    pole = json.loads(call('/api/weather/tec-at', 'lat=90&lon=0')[2])
    assert pole['glotec']['cellLat'] == 88.75 and pole['code']['cellLat'] == 87.5


@pytest.mark.parametrize('query', ['', 'lat=10', 'lon=10', 'lat=91&lon=0', 'lat=0&lon=361', 'lat=abc&lon=0', 'lat=nan&lon=0', 'lat=0&lon=inf'])
@pytest.mark.parametrize('path', ['/api/weather/tec-at', '/api/weather/tec-series'])
def test_tec_at_and_series_refuse_bad_input(weather, path, query):
    ps.publish('weather')
    assert call(path, query)[0].startswith('400')


def test_tec_at_without_any_map_is_404(weather):
    ps.publish('weather')
    assert call('/api/weather/tec-at', 'lat=0&lon=0')[0].startswith('404')


def test_the_series_runs_over_the_stored_maps(weather):
    holdTec(NOW, glotecAges=(30, 20, 10, 1), codeHours=3)
    data = json.loads(call('/api/weather/tec-series', 'lat=-21&lon=102')[2])
    glotec = data['glotec']
    assert glotec['t'] == sorted(glotec['t']) and len(glotec['t']) == 4 and (glotec['cellLat'], glotec['cellLon']) == (-21.25, 102.5)
    assert glotec['tec'] == [7.9 + 30, 7.9 + 20, 7.9 + 10, 7.9 + 1] or [round(v, 1) for v in glotec['tec']] == [37.9, 27.9, 17.9, 8.9]
    assert glotec['observed'] == [False] * 4 and data['anomalyUnit'] == 'TECU (inferred)'
    assert len(glotec['foF2']) == 4 and all(4.0 < v < 4.5 for v in glotec['foF2']) and len(glotec['anomaly']) == 4
    code = data['code']
    assert len(code['observed']['t']) == 3 and len(code['prediction']['t']) == 3 and code['prediction']['product'] == ['pred1'] * 3
    assert code['observed']['t'][-1] < code['prediction']['t'][0] and code['observed']['t'] == sorted(code['observed']['t'])
    assert 'indicative' in data['foF2Note'] and (code['cellLat'], code['cellLon']) == (-20.0, 100.0)
    assert call('/api/weather/tec-series', 'lat=-21&lon=102', {'HTTP_ACCEPT_ENCODING': 'gzip'})[1]['Content-Encoding'] == 'gzip'


def test_the_series_drops_predictions_for_hours_already_observed(weather):
    holdTec(NOW, codeHours=2)
    nearest = (NOW + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
    db = tec.openDb(dbPaths.dbPath(dbPaths.TEC_DB))
    tec.storeMaps(db, [codeMapAt(stamp(nearest), 'prediction', 'pred1', stamp(nearest - timedelta(hours=11)), offset=300)])
    db.close()
    ps.publish('weather')
    code = json.loads(call('/api/weather/tec-series', 'lat=0&lon=0')[2])['code']
    assert stamp(nearest) in code['observed']['t'] and stamp(nearest) not in code['prediction']['t']


# --- tec-latest: NOAA on demand ------------------------------------------------------

class Noaa:
    """Stand-in for NOAA's server: fetch(url) -> (status, text); counts requests and can be slowed or broken."""

    def __init__(self, valid='2026-10-24T20:45:00Z', delay=0.0, broken=False):
        self.valid, self.delay, self.broken, self.asked = valid, delay, broken, []
        self.lock = threading.Lock()

    def __call__(self, url, binary=False):
        with self.lock:
            self.asked.append(url.rsplit('/', 1)[-1] or 'listing')
        time.sleep(self.delay)
        if self.broken:
            raise OSError('connection refused')
        if url == tec.GLOTEC_URL:
            name = 'glotec_icao_' + self.valid.replace('-', '').replace(':', '') + '.geojson'
            return 200, LISTING.split('<a href="glotec_icao_20260923')[0] + f'<a href="{name}">{name}</a> 2026-10-24 21:09  2.4M'
        return 200, glotecAt(self.valid)


def latest(headers=None):
    return call('/api/weather/tec-latest', '', {'HTTP_ACCEPT_ENCODING': 'gzip', **(headers or {})})


def test_latest_fetches_when_nothing_is_held_then_serves_from_memory(weather, monkeypatch):
    noaa = Noaa()
    monkeypatch.setattr(server, 'tec_fetch', noaa)
    ps.publish('weather')
    status, headers, body = latest()
    record = json.loads(gzip.decompress(body))
    assert status == '200 OK' and record['validUtc'] == '2026-10-24T20:45:00Z' and record['source'] == 'glotec' and len(body) < 40000
    assert noaa.asked == ['listing', 'glotec_icao_20261024T204500Z.geojson'] and 'X-Tec-Stale' not in headers
    assert latest()[0] == '200 OK' and len(noaa.asked) == 2                 # within 30 minutes: nothing asked
    assert latest({'HTTP_IF_NONE_MATCH': headers['ETag']})[0].startswith('304')


def test_latest_does_not_fetch_a_map_it_holds_and_asks_again_only_after_30_minutes(weather, monkeypatch):
    holdTec(NOW, glotecAges=(1,))
    newest = stamp(NOW - timedelta(hours=1))
    noaa = Noaa(valid=newest)
    monkeypatch.setattr(server, 'tec_fetch', noaa)
    assert json.loads(gzip.decompress(latest()[2]))['validUtc'] == newest
    assert noaa.asked == ['listing']                                         # the listing only: the map is held
    server._tec_latest['checkedAt'] -= server.TEC_KEEP_SEC + 1
    noaa.valid = stamp(NOW)
    assert json.loads(gzip.decompress(latest()[2]))['validUtc'] == stamp(NOW)
    assert len(noaa.asked) == 3 and noaa.asked[1] == 'listing' and noaa.asked[2].startswith('glotec_icao_')


def test_two_requests_at_once_share_one_fetch(weather, monkeypatch):
    noaa = Noaa(delay=0.4)
    monkeypatch.setattr(server, 'tec_fetch', noaa)
    ps.publish('weather')
    results = []
    threads = [threading.Thread(target=lambda: results.append(latest())) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r[0] for r in results] == ['200 OK'] * 3 and len({r[2] for r in results}) == 1
    assert noaa.asked.count('listing') == 1 and len(noaa.asked) == 2


def test_latest_when_noaa_fails_serves_the_held_map_marked_stale_and_waits_before_asking_again(weather, monkeypatch):
    holdTec(NOW, glotecAges=(2,))
    noaa = Noaa(broken=True)
    monkeypatch.setattr(server, 'tec_fetch', noaa)
    status, headers, body = latest()
    assert status == '200 OK' and headers['X-Tec-Stale'] == '1' and json.loads(gzip.decompress(body))['validUtc'] == stamp(NOW - timedelta(hours=2))
    assert latest()[1]['X-Tec-Stale'] == '1' and len(noaa.asked) <= 3        # the computed-name fallback tried; then left alone
    count = len(noaa.asked)
    latest()
    assert len(noaa.asked) == count


def test_latest_with_nothing_held_and_noaa_down_is_503(weather, monkeypatch):
    monkeypatch.setattr(server, 'tec_fetch', Noaa(broken=True))
    ps.publish('weather')
    assert latest()[0].startswith('503')


def test_latest_without_gzip_gives_plain_json(weather, monkeypatch):
    monkeypatch.setattr(server, 'tec_fetch', Noaa())
    ps.publish('weather')
    status, headers, body = call('/api/weather/tec-latest')
    assert status == '200 OK' and 'Content-Encoding' not in headers and json.loads(body)['nLon'] == 72


def syntheticGlotec(tecs, anoms, flags):
    n = len(tecs)
    return {'validUtc': '2026-10-25T10:55:00Z', 'latMin': -88.75, 'latStep': 2.5, 'lonMin': -177.5, 'lonStep': 5, 'nLon': n, 'tec': tecs, 'anom': anoms, 'q': flags}


def test_summary_counts_only_well_observed_cells_and_takes_the_third_largest_fraction():
    # tenths of TECU: medians (tec - anom) are 100, 100, 100, 100, 100, 50 (too small), 100 (flag 2: not well observed), 100 (flag 0)
    record = syntheticGlotec([180, 60, 130, 110, 90, 90, 300, 1800], [80, -40, 30, 10, -10, 40, 200, 1700], [5, 4, 3, 5, 3, 5, 2, 0])
    out = server.tec_summary_of(record)
    assert out['cellsCounted'] == 5                       # the 50-tenths median and the flag 2 and 0 cells are left out
    assert out['anomalyLargestFraction'] == 0.8 and out['anomalyThirdFraction'] == 0.3
    assert out['tecMaxObserved'] == {'tec': 30.0, 'lat': -88.75, 'lon': -177.5 + 6 * 5, 'flag': 2}      # flag 0 (the 180 TECU model value) is not an observation
    few = server.tec_summary_of(syntheticGlotec([180, 140], [80, -40], [5, 5]))
    assert few['anomalyThirdFraction'] is None and few['anomalyLargestFraction'] == 0.8


def test_summary_endpoint_serves_the_stored_map_and_never_asks_noaa(weather, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('tec-summary must not reach NOAA')
    monkeypatch.setattr(server, 'tec_fetch', refuse)
    ps.publish('weather')
    assert call('/api/weather/tec-summary')[0].startswith('404')
    holdTec(NOW, glotecAges=(1,))
    status, headers, body = call('/api/weather/tec-summary')
    data = json.loads(body)
    assert status.startswith('200') and data['validUtc'] == stamp(NOW - timedelta(hours=1))
    assert set(data) == {'validUtc', 'cellsCounted', 'anomalyThirdFraction', 'anomalyLargestFraction', 'tecMaxObserved'}
    assert data['tecMaxObserved']['flag'] >= 1 and data['cellsCounted'] > 0


def test_latest_fields_sends_only_the_lists_asked_for_and_keeps_the_rest(weather, monkeypatch):
    holdTec(NOW, glotecAges=(1,))
    monkeypatch.setattr(server, 'tec_fetch', Noaa(valid=stamp(NOW - timedelta(hours=1))))
    full = latest()
    status, headers, body = call('/api/weather/tec-latest', 'fields=q,tec,anom', {'HTTP_ACCEPT_ENCODING': 'gzip'})
    assert status == '200 OK' and headers['Content-Encoding'] == 'gzip'
    trimmed, whole = json.loads(gzip.decompress(body)), json.loads(gzip.decompress(full[2]))
    assert set(whole) - set(trimmed) == {'nmf2', 'hmf2'}
    assert all(trimmed[k] == whole[k] for k in trimmed) and trimmed['q'] == whole['q']
    assert len(body) < len(full[2]) * 0.8                                     # about a third smaller
    again = call('/api/weather/tec-latest', 'fields=anom,q,tec', {'HTTP_ACCEPT_ENCODING': 'gzip'})
    assert again[1]['ETag'] == headers['ETag'] and again[2] == body            # field order does not matter; packed once
    assert call('/api/weather/tec-latest', 'fields=anom,q,tec', {'HTTP_ACCEPT_ENCODING': 'gzip', 'HTTP_IF_NONE_MATCH': headers['ETag']})[0].startswith('304')
    assert headers['ETag'] != full[1]['ETag']
    plain = call('/api/weather/tec-latest', 'fields=q')
    assert set(json.loads(plain[2])) & {'tec', 'anom', 'nmf2', 'hmf2'} == set() and 'Content-Encoding' not in plain[1]


@pytest.mark.parametrize('query', ['fields=tec,nope', 'fields=TEC', 'fields=tec;q'])
def test_latest_fields_refuses_unknown_names(weather, monkeypatch, query):
    monkeypatch.setattr(server, 'tec_fetch', lambda *a, **k: (_ for _ in ()).throw(AssertionError('NOAA must not be asked')))
    ps.publish('weather')
    assert call('/api/weather/tec-latest', query)[0].startswith('400')
