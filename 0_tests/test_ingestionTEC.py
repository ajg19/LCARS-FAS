"""Tests for scripts/ingestionTEC.py -- against a temporary database and recorded files only (nothing
touches the network): the CODE rapid file (23 Oct 2026, issued 24 Oct 08:01), the CODE 1-day prediction
(24 Oct, issued 08:15), NOAA's GloTEC map valid 24 Oct 18:35 and the GloTEC directory listing of 24 Oct 21:14
(0_tests/fixtures)."""

import gzip
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(TESTS_DIR), 'scripts'))
import ingestionTEC as tec  # noqa: E402
from spaceWeatherSamples import FeedError  # noqa: E402

NOW = datetime(2026, 10, 24, 9, 15)


def raw(name):
    with open(os.path.join(TESTS_DIR, 'fixtures', name), 'rb') as f:
        return f.read()


def text(name):
    data = raw(name)
    return (gzip.decompress(data) if name.endswith('.gz') else data).decode('utf-8')


RAPID, P0D, GLOTEC, LISTING = text('codeGimRAP_2026296.INX.gz'), text('codeGimP0D_2026297.INX.gz'), text('glotecMap_20261024T1835.json.gz'), text('glotecListing_20261024T2114.html')


def prediction(days):
    """The 1-day prediction passed off as the 2-day or 5-day one (the fixtures hold only the 1-day file)."""
    return P0D.replace("CODE'S 1-DAY PREDICTED", f"CODE'S {days}-DAY PREDICTED")


def glotecAt(valid):
    data = json.loads(GLOTEC)
    data['time_tag'] = valid
    return json.dumps(data)


@pytest.fixture
def db(tmp_path):
    conn = tec.openDb(str(tmp_path / 'ingestionTEC.db'))
    yield conn
    conn.close()


class FakeSite:
    """fetch(url, binary=False) -> (status, body): serves what it is given, 404 for the rest, and records what was asked."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def __call__(self, url, binary=False):
        self.asked.append(url.rsplit('/', 1)[-1] or url)
        body = self.files.get(url.rsplit('/', 1)[-1] or url)
        if body is None:
            return 404, b'' if binary else ''
        if isinstance(body, int):
            return body, b'' if binary else ''
        return 200, body


def codeSite(**extra):
    return FakeSite({'COD0OPSRAP_20262960000_01D_01H_GIM.INX.gz': raw('codeGimRAP_2026296.INX.gz'),
                     'COD0OPSP0D_20262970000_01D_01H_GIM.INX.gz': raw('codeGimP0D_2026297.INX.gz'),
                     'COD0OPSP1D_20262980000_01D_01H_GIM.INX.gz': gzip.compress(prediction(2).encode()),
                     'COD0OPSP4D_20263010000_01D_01H_GIM.INX.gz': gzip.compress(prediction(5).encode()), **extra})


# --- CODE ----------------------------------------------------------------------

def test_the_file_names_are_the_day_the_maps_cover():
    assert tec.codeFileName('COD0OPSRAP', datetime(2026, 10, 23)) == 'COD0OPSRAP_20262960000_01D_01H_GIM.INX.gz'
    assert tec.codeFileName('COD0OPSP4D', datetime(2026, 12, 31)) == 'COD0OPSP4D_20263650000_01D_01H_GIM.INX.gz'


def test_the_prediction_file_gives_25_hourly_maps_on_the_grid():
    maps = tec.parseIonex(P0D, 'pred1', 'prediction', '1-DAY PREDICTED')
    assert len(maps) == 25
    issued, valid, record = maps[0]
    assert (issued, valid) == ('2026-10-24T08:15:00Z', '2026-10-24T00:00:00Z') and maps[-1][1] == '2026-10-25T00:00:00Z'
    assert [m[1] for m in maps] == [(datetime(2026, 10, 24) + timedelta(hours=h)).strftime('%Y-%m-%dT%H:00:00Z') for h in range(25)]
    assert len(record['rows']) == 71 and all(len(r) == 73 for r in record['rows'])
    assert record['rows'][0][:3] == [84, 84, 84] and record['rows'][1][0] == 92      # 8.4 and 9.2 TECU at 87.5 and 85 N, 180 W
    assert (record['source'], record['product'], record['kind'], record['unit']) == ('code', 'pred1', 'prediction', 'tenthsTECU')
    assert (record['latMax'], record['latStep'], record['lonMin'], record['lonStep']) == (87.5, -2.5, -180, 5)


def test_the_rapid_file_keeps_the_tec_maps_and_ignores_the_rms_maps_and_bias_block():
    maps = tec.parseIonex(RAPID, 'rapid', 'observed', 'RAPID')
    assert len(maps) == 25 and maps[0][:2] == ('2026-10-24T08:01:00Z', '2026-10-23T00:00:00Z')
    assert maps[0][2]['kind'] == 'observed'
    samples = tec.codeSamples(maps)
    assert len(samples) == 75
    assert samples[0][:2] == ('codeTecMax', '2026-10-23T00:00:00Z') and samples[0][2] == 95.7     # the file's own "peak TEC" comment: 957
    top = {s[0]: s[2] for s in samples if s[1] == '2026-10-23T00:00:00Z'}
    assert -90 <= top['codeTecMaxLat'] <= 90 and -180 <= top['codeTecMaxLon'] <= 180


def test_predictions_give_no_summary_samples():
    assert tec.codeSamples(tec.parseIonex(P0D, 'pred1', 'prediction', '1-DAY PREDICTED')) == []


def test_9999_is_no_value():
    damaged = P0D.replace('   84   84   84   84   84   84   83', ' 9999   84   84   84   84   84   83', 1)
    assert tec.parseIonex(damaged, 'pred1', 'prediction', '1-DAY PREDICTED')[0][2]['rows'][0][:2] == [None, 84]


@pytest.mark.parametrize('what, damage', [
    ('cut off', lambda t: '\n'.join(t.splitlines()[:2000])),
    ('a map missing', lambda t: t.replace('    25                                                      # OF MAPS IN FILE',
                                          '    26                                                      # OF MAPS IN FILE')),
    ('a different grid', lambda t: t.replace('    87.5 -87.5  -2.5', '    87.5 -87.5  -2.0', 1)),
    ('another height', lambda t: t.replace('   450.0 450.0   0.0', '   400.0 400.0   0.0', 1)),
    ('another exponent', lambda t: t.replace('    -1                                                      EXPONENT', '    -2                                                      EXPONENT')),
    ('a word instead of a value', lambda t: t.replace('   84   84   84   84   84   84   83', '   84   84   xx   84   84   84   83', 1)),
    ('a silly value', lambda t: t.replace('   84   84   84   84   84   84   83', '   84   84 8400   84   84   84   83', 1)),
    ('a short row', lambda t: t.replace('   83   83   84\n', '   83   83\n', 1)),
    ('not IONEX', lambda t: '<html>503 Service Unavailable</html>'),
    ('the wrong product', lambda t: t.replace("CODE'S 1-DAY PREDICTED", "CODE'S RAPID")),
    ('no issue time', lambda t: t.replace('PGM / RUN BY / DATE', 'NOTHING')),
])
def test_surprises_reject_the_whole_file(what, damage):
    with pytest.raises(FeedError):
        tec.parseIonex(damage(P0D), 'pred1', 'prediction', '1-DAY PREDICTED')


def test_a_first_run_fetches_each_file_once_and_stores_the_maps(db):
    site = codeSite()
    changes, failed, note = tec.runCode(db, site, NOW)
    assert not failed and changes > 0
    assert site.asked == ['COD0OPSRAP_20262960000_01D_01H_GIM.INX.gz', 'COD0OPSRAP_20262950000_01D_01H_GIM.INX.gz',
                          'COD0OPSP0D_20262970000_01D_01H_GIM.INX.gz', 'COD0OPSP1D_20262980000_01D_01H_GIM.INX.gz',
                          'COD0OPSP4D_20263010000_01D_01H_GIM.INX.gz']
    assert db.execute('SELECT product, COUNT(*) FROM tecMaps GROUP BY product ORDER BY product').fetchall() == [
        ('pred1', 25), ('pred2', 25), ('pred5', 25), ('rapid', 25)]
    assert db.execute('SELECT COUNT(*) FROM sourceFiles').fetchone()[0] == 4          # the 404 is not recorded
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'codeTecMax'").fetchone()[0] == 25
    assert 'rapid 2026-10-22 not yet published' in note and 'FAILED' not in note
    kind, gz = db.execute("SELECT kind, gz FROM tecMaps WHERE product = 'rapid' ORDER BY validUtc LIMIT 1").fetchone()
    assert kind == 'observed' and tec.unpackMap(gz)['validUtc'] == '2026-10-23T00:00:00Z' and len(gz) < 20000


def test_a_file_already_held_is_never_fetched_again(db):
    tec.runCode(db, codeSite(), NOW)
    again = codeSite()
    changes, failed, note = tec.runCode(db, again, NOW)
    assert again.asked == ['COD0OPSRAP_20262950000_01D_01H_GIM.INX.gz'] and (changes, failed) == (0, False)   # only the catch-up that is still missing
    late = codeSite(**{'COD0OPSRAP_20262950000_01D_01H_GIM.INX.gz': raw('codeGimRAP_2026296.INX.gz')})
    assert tec.runCode(db, late, NOW)[1] is False and late.asked == ['COD0OPSRAP_20262950000_01D_01H_GIM.INX.gz']
    assert db.execute('SELECT COUNT(*) FROM sourceFiles').fetchone()[0] == 5


def test_before_codes_issue_time_nothing_is_a_failure(db):
    changes, failed, note = tec.runCode(db, FakeSite({}), NOW)
    assert (changes, failed) == (0, False) and 'not yet published' in note


def test_a_bad_file_fails_the_run_but_not_the_other_files(db):
    site = codeSite(**{'COD0OPSP0D_20262970000_01D_01H_GIM.INX.gz': gzip.compress(b'<html>nope</html>'),
                       'COD0OPSP1D_20262980000_01D_01H_GIM.INX.gz': 500})
    changes, failed, note = tec.runCode(db, site, NOW)
    assert failed and changes > 0 and note.count('FAILED') == 1
    assert {r[0] for r in db.execute('SELECT DISTINCT product FROM tecMaps')} == {'rapid', 'pred5'}
    assert db.execute('SELECT COUNT(*) FROM sourceFiles').fetchone()[0] == 2          # a failed file is tried again next time


def test_not_gzip_is_a_failure_with_nothing_stored(db):
    changes, failed, _ = tec.runCode(db, FakeSite({'COD0OPSRAP_20262960000_01D_01H_GIM.INX.gz': b'not gzip at all'}), NOW)
    assert failed and db.execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0] == 0


def test_maps_more_than_seven_days_old_are_deleted_and_future_ones_kept(db):
    tec.runCode(db, codeSite(), NOW)
    before = db.execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0]
    assert tec.prune(db, datetime(2026, 10, 30, 0, 30)) == 0                # cutoff 23 Oct 00:00: all newer or equal
    removed = tec.prune(db, datetime(2026, 10, 31, 12))                    # cutoff 24 Oct 12:00
    assert removed > 0 and db.execute('SELECT MIN(validUtc) FROM tecMaps').fetchone()[0] >= '2026-10-24T12:00:00Z'
    assert db.execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0] == before - removed
    assert db.execute("SELECT COUNT(*) FROM tecMaps WHERE product = 'pred5'").fetchone()[0] > 0       # later maps are kept
    assert db.execute("SELECT COUNT(*) FROM tecMaps WHERE product = 'rapid'").fetchone()[0] == 0
    tec.prune(db, datetime(2026, 12, 1))
    assert db.execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0] == 0 and db.execute('SELECT COUNT(*) FROM sourceFiles').fetchone()[0] == 0


def test_a_rerun_of_the_same_maps_changes_nothing(db):
    maps = tec.parseIonex(RAPID, 'rapid', 'observed', 'RAPID')
    assert tec.storeMaps(db, maps, tec.codeSamples(maps)) == 25 + 75
    assert tec.storeMaps(db, maps, tec.codeSamples(maps)) == 0


# --- GloTEC --------------------------------------------------------------------

def test_the_glotec_map_becomes_a_compact_grid():
    record, samples = tec.parseGlotec(GLOTEC)
    assert record['validUtc'] == record['issuedUtc'] == '2026-10-24T18:35:00Z' and record['kind'] == 'observed'
    assert all(len(record[k]) == 5184 for k in ('tec', 'anom', 'nmf2', 'hmf2', 'q'))
    assert (record['latMin'], record['latStep'], record['lonMin'], record['lonStep'], record['nLat'], record['nLon']) == (-88.75, 2.5, -177.5, 5, 72, 72)
    assert (record['tec'][0], record['anom'][0], record['nmf2'][0], record['hmf2'][0], record['q'][0]) == (93, 16, 30, 316, 0)   # 177.5 W, 88.75 S
    index = 27 * 72 + 56                                                                                                           # 21.25 S, 102.5 E
    assert (record['tec'][index], record['anom'][index], record['nmf2'][index], record['hmf2'][index]) == (79, -12, 23, 337)
    assert {s[0]: s[2] for s in samples} == {'glotecTecMax': 67.7, 'glotecTecMaxLat': -11.25, 'glotecTecMaxLon': -27.5}
    assert set(record['q']) == {0, 1, 2, 3, 4, 5}
    assert len(tec.packMap(record)) < 40000                                                                                        # a few tens of kB


def damaged(change):
    data = json.loads(GLOTEC)
    change(data)
    return json.dumps(data)


@pytest.mark.parametrize('what, change', [
    ('a cell missing', lambda d: d['features'].pop()),
    ('a cell twice', lambda d: d['features'].__setitem__(5, d['features'][6])),
    ('a cell off the grid', lambda d: d['features'][3]['geometry'].__setitem__('coordinates', [-176.0, -88.75])),
    ('latitude off the grid', lambda d: d['features'][3]['geometry'].__setitem__('coordinates', [-172.5, 90.0])),
    ('no time', lambda d: d.pop('time_tag')),
    ('a bad time', lambda d: d.__setitem__('time_tag', 'yesterday')),
    ('a word for a number', lambda d: d['features'][0]['properties'].__setitem__('tec', 'high')),
    ('a missing property', lambda d: d['features'][0]['properties'].pop('NmF2')),
    ('not a collection', lambda d: d.__setitem__('type', 'Feature')),
    ('no features', lambda d: d.__setitem__('features', [])),
    ('a float flag', lambda d: d['features'][0]['properties'].__setitem__('quality_flag', 1.5)),
])
def test_glotec_surprises_reject_the_whole_map(what, change):
    with pytest.raises(FeedError):
        tec.parseGlotec(damaged(change))


def test_glotec_rejects_html_and_nothing():
    for body in ('<html>503</html>', '', '[]'):
        with pytest.raises(FeedError):
            tec.parseGlotec(body)


def test_a_missing_value_is_null_not_zero():
    record, _ = tec.parseGlotec(damaged(lambda d: d['features'][0]['properties'].__setitem__('NmF2', None)))
    assert record['nmf2'][0] is None and record['nmf2'][1] == 30


def test_the_listing_names_the_newest_map():
    assert tec.newestInListing(LISTING) == '2026-10-24T20:45:00Z'
    with pytest.raises(FeedError):
        tec.newestInListing('<html>Index of /nothing</html>')


@pytest.mark.parametrize('now, back, expected', [
    (datetime(2026, 10, 24, 21, 14), 0, '2026-10-24T20:35:00Z'),
    (datetime(2026, 10, 24, 21, 14), 1, '2026-10-24T20:25:00Z'),
    (datetime(2026, 10, 24, 21, 20), 0, '2026-10-24T20:45:00Z'),
    (datetime(2026, 10, 24, 21, 19, 59), 0, '2026-10-24T20:45:00Z'),
    (datetime(2026, 10, 24, 21, 25), 0, '2026-10-24T20:55:00Z'),
    (datetime(2026, 10, 25, 0, 10), 1, '2026-10-24T23:25:00Z')])
def test_the_computed_name_is_30_minutes_back_at_a_minute_ending_in_5(now, back, expected):
    assert tec.computedValid(now, back) == expected
    assert tec.glotecName(datetime.strptime(expected, '%Y-%m-%dT%H:%M:%SZ')).startswith('glotec_icao_')


def glotecSite(**extra):
    files = {tec.GLOTEC_URL: LISTING, 'glotec_icao_20261024T204500Z.geojson': glotecAt('2026-10-24T20:45:00Z'),
             'glotec_icao_20261024T203500Z.geojson': glotecAt('2026-10-24T20:35:00Z'),
             'glotec_icao_20261024T202500Z.geojson': glotecAt('2026-10-24T20:25:00Z'), **extra}
    return FakeSite(files)


GNOW = datetime(2026, 10, 24, 21, 14)


def test_the_newest_listed_map_is_fetched_once_and_stored(db):
    site = glotecSite()
    changes, failed, note = tec.runGlotec(db, site, GNOW)
    assert not failed and changes == 1 + 3 and site.asked == [tec.GLOTEC_URL, 'glotec_icao_20261024T204500Z.geojson']
    assert db.execute("SELECT validUtc, kind FROM tecMaps WHERE source = 'glotec'").fetchall() == [('2026-10-24T20:45:00Z', 'observed')]
    assert db.execute("SELECT value FROM samples WHERE series = 'glotecTecMax'").fetchone()[0] == 67.7
    again = glotecSite()
    assert tec.runGlotec(db, again, GNOW)[:2] == (0, False) and again.asked == [tec.GLOTEC_URL]      # the listing, no map


def test_without_a_listing_the_computed_name_is_used_and_one_step_back_on_a_404(db):
    site = glotecSite(**{tec.GLOTEC_URL: 503})
    del site.files['glotec_icao_20261024T203500Z.geojson']
    changes, failed, _ = tec.runGlotec(db, site, GNOW)
    assert not failed and site.asked == [tec.GLOTEC_URL, 'glotec_icao_20261024T203500Z.geojson', 'glotec_icao_20261024T202500Z.geojson']
    assert db.execute("SELECT validUtc FROM tecMaps").fetchone()[0] == '2026-10-24T20:25:00Z'
    assert tec.runGlotec(db, FakeSite({tec.GLOTEC_URL: 503}), GNOW)[:2] == (0, False)       # 20:25 is held, so nothing more is fetched


def test_with_neither_listing_nor_maps_the_run_fails_after_two_names(db):
    missing = FakeSite({tec.GLOTEC_URL: 503})
    changes, failed, note = tec.runGlotec(db, missing, GNOW)
    assert failed and changes == 0 and len(missing.asked) == 3 and 'HTTP 404' in note       # the listing and two names, no more


def test_an_empty_listing_falls_back_too(db):
    site = glotecSite(**{tec.GLOTEC_URL: '<html>Index of /empty</html>'})
    assert tec.runGlotec(db, site, GNOW)[:2] == (4, False) and site.asked[1] == 'glotec_icao_20261024T203500Z.geojson'


def test_a_map_that_is_not_the_one_asked_for_is_refused(db):
    site = glotecSite(**{'glotec_icao_20261024T204500Z.geojson': GLOTEC})        # says 18:35
    changes, failed, note = tec.runGlotec(db, site, GNOW)
    assert failed and 'asked for' in note and db.execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0] == 0


def test_a_broken_map_stores_nothing(db):
    changes, failed, _ = tec.runGlotec(db, glotecSite(**{'glotec_icao_20261024T204500Z.geojson': '<html>'}), GNOW)
    assert failed and changes == 0 and db.execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0] == 0


def test_glotec_keeps_seven_days_and_deletes_the_rest(db):
    for days in (9, 8, 6, 1):
        valid = (GNOW - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        record, samples = tec.parseGlotec(glotecAt(valid))
        tec.storeMaps(db, [(valid, valid, record)], samples)
    assert db.execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0] == 4
    changes, failed, note = tec.runGlotec(db, glotecSite(), GNOW)
    assert not failed and 'old maps deleted' in note
    assert db.execute('SELECT COUNT(*) FROM tecMaps').fetchone()[0] == 3        # 6 days, 1 day and the new one


def test_main_records_the_run(tmp_path, monkeypatch):
    path = str(tmp_path / 'ingestionTEC.db')
    monkeypatch.setattr(tec, 'openDb', lambda: sqlite3.connect(path))
    monkeypatch.setattr(tec, 'runGlotec', lambda db, *a: (0, False, 'newest map already held'))
    assert tec.main(['--job', 'tecGlotec']) == 0
    row = sqlite3.connect(path).execute('SELECT job, succeeded, note FROM ingestionRuns').fetchone()
    assert row == ('tecGlotec', 1, 'newest map already held')
