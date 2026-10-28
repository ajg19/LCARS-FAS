"""Tests for scripts/ingestionSWPC.py -- against a temporary database and
NOAA SWPC responses recorded on 2026-10-24 and trimmed (0_tests/fixtures/,
swpc*); nothing touches the network or the real databases/ingestionSWPC.db."""

import json
import re
import os
import sqlite3
import sys
from datetime import datetime

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(TESTS_DIR), 'scripts'))
import ingestionSWPC as isw  # noqa: E402
from spaceWeatherSamples import FeedError  # noqa: E402

# feed name -> fixture file
FIXTURES = {
    'scales': 'swpcScales.json', 'kp1m': 'swpcKp1m.json', 'protons': 'swpcProtons.json', 'xray': 'swpcXray.json',
    'hemiPower': 'swpcHemiPower.txt', 'l1Mag': 'swpcMag.json', 'l1Wind': 'swpcWind.json', 'f107': 'swpcF107.json',
    'forecast45': 'swpc45day.json', 'flares': 'swpcFlares.json', 'radioFlux': 'swpcRadioFlux.json',
    'events': 'swpcEvents.json', 'kp': 'swpcKp.json', 'dst': 'swpcDst.json', 'forecast3day': 'swpc3day.txt',
    'outlook27day': 'swpc27day.txt', 'ovation': 'swpcOvation.json', 'drap': 'swpcDrap.txt',
}


def fixtureText(name):
    with open(os.path.join(TESTS_DIR, 'fixtures', FIXTURES.get(name, name)), encoding='utf-8') as f:
        return f.read()


def fixtureJson(name):
    return json.loads(fixtureText(name))


def fetcher(replace=None, fail=()):
    """A fetch() stand-in: each feed's URL answers with its fixture, unless
    `replace` gives other text for that feed or it is in `fail`."""
    byUrl = {isw.BASE_URL + path: name for name, (path, _) in isw.FEEDS.items()}
    replace = replace or {}

    def fetch(url):
        name = byUrl[url]
        if name in fail:
            raise Exception('HTTP 503')
        return replace[name] if name in replace else fixtureText(name)
    return fetch


@pytest.fixture
def db(tmp_path):
    conn = isw.openDb(str(tmp_path / 'ingestionSWPC.db'))
    yield conn
    conn.close()


def series(rows, name):
    return {r[1]: r[2] for r in rows if r[0] == name}


def count(db, table='samples', where='1'):
    return db.execute(f'SELECT COUNT(*) FROM {table} WHERE {where}').fetchone()[0]


# --- swpcFast feeds ---------------------------------------------------------------

def test_scales_observed_and_forecast():
    rows, events = isw.parseScales(fixtureText('scales'))
    assert events == []
    assert series(rows, 'noaaScaleG') == {'2026-10-23T15:06:00Z': 0.0, '2026-10-24T15:06:00Z': 0.0}
    assert series(rows, 'noaaForecastRMinorProb')['2026-10-25T00:00:00Z'] == 15.0
    assert series(rows, 'noaaForecastSProb')['2026-10-26T00:00:00Z'] == 1.0
    assert {r[4] for r in rows if r[0].startswith('noaaForecast')} == {'forecast'}


def test_scales_without_the_expected_days_are_rejected():
    data = fixtureJson('scales')
    del data['3']
    with pytest.raises(FeedError):
        isw.parseScales(json.dumps(data))


def test_one_minute_kp():
    rows, _ = isw.parseKp1m(fixtureText('kp1m'))
    assert len(rows) == 4 and rows[0][0] == 'swpcKp1m' and rows[0][1] == '2026-10-24T09:07:00Z' and rows[0][3] == 'Kp'


def test_protons_have_one_series_per_energy_threshold():
    rows, _ = isw.parseProtons(fixtureText('protons'))
    names = {r[0] for r in rows}
    assert names == {f'goesProtonGE{n}MeV' for n in (1, 5, 10, 30, 50, 60, 100, 500)}
    assert len(rows) == 16 and {r[3] for r in rows} == {'pfu'} and {r[4] for r in rows} == {'GOES-18'}


def test_protons_with_an_unknown_energy_label_are_rejected():
    data = fixtureJson('protons')
    data[0]['energy'] = '1-2 MeV'
    with pytest.raises(FeedError, match='energy'):
        isw.parseProtons(json.dumps(data))


def test_xray_channels_are_separated_and_contamination_is_flagged():
    raw = fixtureJson('xray')
    assert any('electron_contaminaton' in r for r in raw)   # NOAA's misspelt key, as recorded
    rows, _ = isw.parseXray(fixtureText('xray'))
    assert {r[0] for r in rows} == {'goesXrayLong', 'goesXrayShort'}
    assert {r[4] for r in rows if r[0] == 'goesXrayLong'} == {'GOES-18'}
    assert {r[4] for r in rows if r[0] == 'goesXrayShort'} == {'GOES-18 contaminated'}
    assert all(r[3] == 'W/m2' for r in rows)


def test_xray_values_at_the_processing_floor_are_marked():
    data = fixtureJson('xray')
    short = next(r for r in data if r['energy'] == '0.05-0.4nm')
    short['flux'] = 9.99999972e-10         # 1e-9 as float32: max(1e-9, observed - electron correction)
    rows, _ = isw.parseXray(json.dumps(data))
    floored = [r for r in rows if r[2] is not None and r[2] <= 1.0001e-9]
    assert len(floored) == 1 and floored[0][4].endswith(' floor') and floored[0][0] == 'goesXrayShort'
    assert not any('floor' in r[4] for r in rows if r not in floored)


def test_xray_accepts_the_key_spelt_correctly_should_noaa_fix_it():
    text = fixtureText('xray').replace('electron_contaminaton', 'electron_contamination')
    assert len(isw.parseXray(text)[0]) == 6


def test_xray_without_either_spelling_is_rejected():
    text = fixtureText('xray').replace('electron_contaminaton', 'something_else')
    with pytest.raises(FeedError, match='electron_contaminaton'):
        isw.parseXray(text)


def test_xray_with_a_new_channel_is_rejected():
    data = fixtureJson('xray')
    data[0]['energy'] = '0.2-0.9nm'
    with pytest.raises(FeedError, match='channel'):
        isw.parseXray(json.dumps(data))


def test_hemispheric_power_north_and_south():
    rows, _ = isw.parseHemiPower(fixtureText('hemiPower'))
    assert series(rows, 'hemiPowerNorth')['2026-10-24T00:00:00Z'] == 18.0
    assert series(rows, 'hemiPowerSouth')['2026-10-24T00:10:00Z'] == 17.0
    assert len(rows) == 10 and {r[3] for r in rows} == {'GW'}


def test_hemispheric_power_na_is_null_and_junk_is_rejected():
    text = fixtureText('hemiPower') + '2026-10-24_00:25    2026-10-24_01:24      n/a      17\n'
    rows, _ = isw.parseHemiPower(text)
    assert series(rows, 'hemiPowerNorth')['2026-10-24T00:25:00Z'] is None
    assert series(rows, 'hemiPowerSouth')['2026-10-24T00:25:00Z'] == 17.0
    with pytest.raises(FeedError):
        isw.parseHemiPower(text + '2026-10-24_00:30    2026-10-24_01:29      -999      17\n')
    with pytest.raises(FeedError, match='header'):
        isw.parseHemiPower('<html>moved</html>')


# --- swpcSlow feeds ---------------------------------------------------------------

def test_l1_mag_keeps_only_the_active_source_and_leaves_gaps_as_gaps():
    raw = fixtureJson('l1Mag')
    assert {r['source'] for r in raw} == {'IMAP', 'ACE', 'SOLAR1'}   # interleaved
    rows, _ = isw.parseMag(fixtureText('l1Mag'))
    assert {r[0] for r in rows} == {'l1MagBt', 'l1MagBxGSM', 'l1MagByGSM', 'l1MagBzGSM'}
    assert {r[4] for r in rows} == {'SOLAR1'}
    assert sorted(series(rows, 'l1MagBt')) == ['2026-10-24T15:02:00Z', '2026-10-24T15:03:00Z']   # 14:46 had no active row
    assert series(rows, 'l1MagBt')['2026-10-24T15:03:00Z'] == 3.23
    assert {r[3] for r in rows} == {'nT'}


def test_l1_wind_null_reading_stays_null_and_a_minute_without_an_active_row_is_absent():
    rows, _ = isw.parseWind(fixtureText('l1Wind'))
    speed = series(rows, 'l1WindSpeed')
    assert speed['2026-10-23T22:23:00Z'] is None
    assert speed['2026-10-24T15:02:00Z'] == 399.4
    assert '2026-10-24T15:03:00Z' not in speed   # only ACE reported that minute
    assert {r[3] for r in rows if r[0] == 'l1WindDensity'} == {'cm-3'}


def test_l1_rows_with_a_poor_quality_flag_say_so():
    data = fixtureJson('l1Mag')
    for r in data:
        if r['active']:
            r['overall_quality'] = 2
    rows, _ = isw.parseMag(json.dumps(data))
    assert {r[4] for r in rows} == {'SOLAR1 q2'}


def test_l1_without_the_active_flag_or_with_no_active_row_is_rejected():
    data = fixtureJson('l1Mag')
    with pytest.raises(FeedError, match='active'):
        isw.parseMag(json.dumps([{k: v for k, v in r.items() if k != 'active'} for r in data]))
    with pytest.raises(FeedError, match='no row flagged active'):
        isw.parseMag(json.dumps([{**r, 'active': False} for r in data]))


def test_l1_with_text_where_a_number_belongs_is_rejected():
    data = fixtureJson('l1Mag')
    data[-1]['bt'] = 'N/A'
    with pytest.raises(FeedError):
        isw.parseMag(json.dumps(data))


def test_f107_keeps_all_readings_the_noon_one_as_the_daily_series_and_the_90_day_mean_from_noon():
    rows, _ = isw.parseF107(fixtureText('f107'))
    flux = {r[1]: r[4] for r in rows if r[0] == 'swpcF107'}
    assert flux['2026-10-23T20:00:00Z'] == 'Noon' and flux['2026-10-23T22:00:00Z'] == 'Afternoon'
    daily = series(rows, 'swpcF107Daily')
    assert set(daily) == {ts for ts, q in flux.items() if q == 'Noon'}
    assert daily['2026-10-23T20:00:00Z'] == series(rows, 'swpcF107')['2026-10-23T20:00:00Z']
    mean = series(rows, 'swpcF107Mean90')
    assert mean == {'2026-10-23T20:00:00Z': 115.0, '2026-10-22T20:00:00Z': 115.0}
    assert {r[4] for r in rows if r[0] == 'swpcF107Mean90'} == {'trailing mean of the last 90 Noon readings'}
    assert {r[3] for r in rows} == {'sfu'}


def test_f107_flags_a_reading_far_from_its_days_noon_value_as_a_possible_burst():
    def record(hour, flux, schedule):
        return {'time_tag': f'2026-10-13T{hour}:00:00', 'flux': flux, 'reporting_schedule': schedule, 'ninety_day_mean': None}
    rows, _ = isw.parseF107(json.dumps([record('17', 124, 'Morning'), record('20', 136, 'Noon'), record('22', 207, 'Afternoon')]))
    quality = {r[1][11:13]: r[4] for r in rows if r[0] == 'swpcF107'}
    assert quality == {'17': 'Morning', '20': 'Noon', '22': 'Afternoon burst?'}      # median 136: 124 is 9% off; 207 is 52%
    assert [r[2] for r in rows if r[0] == 'swpcF107Daily'] == [136.0]


def test_45_day_forecast_takes_its_units_from_the_feed_except_that_ap_is_unitless():
    rows, _ = isw.parse45Day(fixtureText('forecast45'))
    assert series(rows, 'swpcForecastAp')['2026-10-25T00:00:00Z'] == 18.0
    assert series(rows, 'swpcForecastF107')['2026-10-26T00:00:00Z'] == 95.0
    assert {r[3] for r in rows if r[0] == 'swpcForecastF107'} == {'sfu'}
    assert {r[4] for r in rows} == {'issued 2026-10-24'}
    assert {r[3] for r in rows if r[0] == 'swpcForecastAp'} == {'Ap'}      # NOAA's label is 'nT'; Ap is unitless


def test_45_day_forecast_with_a_new_metric_is_rejected():
    data = fixtureJson('forecast45')
    data['data'][0]['metric'] = 'kp'
    with pytest.raises(FeedError, match='metric'):
        isw.parse45Day(json.dumps(data))


def test_flares_become_events_and_an_empty_week_is_fine():
    rows, events = isw.parseFlares(fixtureText('flares'))
    assert rows == [] and len(events) == 3
    assert events[0][0] == 'flare' and events[0][1] == '2026-10-17T15:22:00Z' and events[0][2] == '2026-10-17T15:22:00Z GOES-18'
    assert events[0][3]['max_class'] == 'C1.4'
    assert isw.parseFlares('[]') == ([], [])


def test_radio_flux_readings_are_events_with_the_quality_text_repaired():
    _, events = isw.parseRadioFlux(fixtureText('radioFlux'))
    assert [e[0] for e in events] == ['radioFlux', 'radioFlux']
    assert events[0][2] == 'San Vito|2026-10-24T10:45:00Z'
    qualities = {d['observed_quality'] for e in events for d in e[3]['details']}
    assert 'Uncertain – unknown cause' in qualities
    assert not any('â' in q for q in qualities)


def test_edited_events_keep_their_type_and_duplicates_by_report_number_stay_distinct():
    _, events = isw.parseEvents(fixtureText('events'))
    assert len(events) == 5 and len({e[2] for e in events}) == 5
    assert {e[0] for e in events} == {'RBR', 'RSP', 'XRA'}
    sag = [e for e in events if e[2].startswith('SAG|RBR')]
    assert len(sag) == 2 and sag[0][1] == sag[1][1] == '2026-10-08T15:40:30Z'


def test_kp_carries_observed_estimated_or_predicted():
    rows, _ = isw.parseKp(fixtureText('kp'))
    assert [r[4] for r in rows] == ['observed', 'observed', 'estimated', 'predicted', 'predicted']
    assert {r[0] for r in rows} == {'swpcKp'}


def test_kp_with_a_new_state_is_rejected():
    data = fixtureJson('kp')
    data[0]['observed'] = 'definitive'
    with pytest.raises(FeedError, match='state'):
        isw.parseKp(json.dumps(data))


def test_dst():
    rows, _ = isw.parseDst(fixtureText('dst'))
    assert len(rows) == 4 and rows[0][0] == 'swpcDst' and rows[0][3] == 'nT'
    assert {r[4] for r in rows} == {'realtime'}      # Kyoto's quick-look values, replaced later by provisional and final ones


def test_three_day_forecast_numbers_and_the_text():
    rows, events = isw.parse3Day(fixtureText('forecast3day'))
    kp = series(rows, 'swpcForecast3dayKp')
    assert len(kp) == 24
    assert kp['2026-10-24T00:00:00Z'] == 2.0 and kp['2026-10-25T06:00:00Z'] == 3.67 and kp['2026-10-26T21:00:00Z'] == 2.33
    assert series(rows, 'swpcForecast3dayS1Prob')['2026-10-25T00:00:00Z'] == 1.0
    assert series(rows, 'swpcForecast3dayR1R2Prob')['2026-10-26T00:00:00Z'] == 10.0
    assert series(rows, 'swpcForecast3dayR3Prob')['2026-10-24T00:00:00Z'] == 1.0
    assert {r[4] for r in rows} == {'issued 2026-10-24T12:30:00Z'}
    assert len(events) == 1 and events[0][:3] == ('forecast3day', '2026-10-24T12:30:00Z', '2026-10-24T12:30:00Z')
    assert 'Rationale' in events[0][3]['text']


def test_three_day_forecast_year_rolls_over_in_december():
    text = fixtureText('forecast3day').replace(':Issued: 2026 Oct 24 1230 UTC', ':Issued: 2026 Dec 30 1230 UTC') \
        .replace('Oct 24', 'Dec 30').replace('Oct 25', 'Dec 31').replace('Oct 26', 'Jan 01')
    rows, _ = isw.parse3Day(text)
    assert max(series(rows, 'swpcForecast3dayKp')) == '2027-01-01T21:00:00Z'


def test_three_day_forecast_without_its_tables_is_rejected():
    text = fixtureText('forecast3day')
    with pytest.raises(FeedError, match='Kp table'):
        isw.parse3Day(text.replace('00-03UT', 'xx-xxUT'))
    with pytest.raises(FeedError, match='Issued'):
        isw.parse3Day(text.replace(':Issued:', ':Posted:'))
    with pytest.raises(FeedError, match='R3'):
        isw.parse3Day(text.replace('R3 or greater', 'R3+'))


def test_27_day_outlook_numbers_and_the_text():
    rows, events = isw.parse27Day(fixtureText('outlook27day'))
    assert len(series(rows, 'swpcOutlook27Ap')) == 27
    assert series(rows, 'swpcOutlook27F107')['2026-10-21T00:00:00Z'] == 105.0
    assert series(rows, 'swpcOutlook27Kp')['2026-10-19T00:00:00Z'] == 5.0
    assert events[0][:3] == ('outlook27day', '2026-10-19T01:41:00Z', '2026-10-19T01:41:00Z')


def test_27_day_outlook_with_too_few_lines_is_rejected():
    short = '\n'.join(fixtureText('outlook27day').splitlines()[:20])
    with pytest.raises(FeedError, match='data lines'):
        isw.parse27Day(short)


# --- Run ------------------------------------------------------------------------

def test_fast_job_stores_its_feeds_and_a_repeat_changes_nothing(db):
    changes, failed, note = isw.runIngestion(db, fetcher(), isw.JOB_FAST)
    assert not failed and changes > 0
    assert note.startswith('scales ')
    names = {r[0] for r in db.execute('SELECT DISTINCT series FROM samples')}
    assert 'goesXrayLong' in names and 'hemiPowerNorth' in names and 'noaaScaleR' in names
    assert 'l1MagBt' not in names   # a slow feed
    assert isw.runIngestion(db, fetcher(), isw.JOB_FAST) == (0, False, note)


def test_slow_job_stores_its_feeds_and_a_repeat_changes_nothing(db):
    changes, failed, note = isw.runIngestion(db, fetcher(), isw.JOB_SLOW)
    assert not failed and changes > 0
    names = {r[0] for r in db.execute('SELECT DISTINCT series FROM samples')}
    assert {'l1MagBt', 'l1WindSpeed', 'swpcF107', 'swpcForecastAp', 'swpcKp', 'swpcDst', 'swpcForecast3dayKp',
            'swpcOutlook27Ap'} <= names
    assert 'goesXrayLong' not in names
    kinds = {r[0] for r in db.execute('SELECT DISTINCT eventType FROM events')}
    assert {'flare', 'radioFlux', 'XRA', 'RBR', 'forecast3day', 'outlook27day'} <= kinds
    assert isw.runIngestion(db, fetcher(), isw.JOB_SLOW)[0] == 0


def test_a_changed_reading_is_a_change_and_nothing_else_is(db):
    isw.runIngestion(db, fetcher(), isw.JOB_FAST)
    data = fixtureJson('kp1m')
    data[0]['estimated_kp'] = 3.33
    changes, failed, _ = isw.runIngestion(db, fetcher({'kp1m': json.dumps(data)}), isw.JOB_FAST)
    assert (changes, failed) == (1, False)


def test_a_surprise_shape_stores_nothing_from_that_feed_and_fails_the_run(db):
    broken = json.dumps([{k: v for k, v in r.items() if k != 'active'} for r in fixtureJson('l1Mag')])
    changes, failed, note = isw.runIngestion(db, fetcher({'l1Mag': broken}), isw.JOB_SLOW)
    assert failed and 'l1Mag: FeedError' in note and 'missing active' in note
    assert count(db, where="series LIKE 'l1Mag%'") == 0
    assert count(db, where="series LIKE 'l1Wind%'") > 0    # the other feeds are independent
    assert changes > 0


def test_a_feed_that_cannot_be_fetched_fails_the_run_and_keeps_what_we_hold(db):
    isw.runIngestion(db, fetcher(), isw.JOB_FAST)
    before = count(db)
    changes, failed, note = isw.runIngestion(db, fetcher(fail=('xray',)), isw.JOB_FAST)
    assert failed and 'xray: Exception: HTTP 503' in note and changes == 0
    assert count(db) == before


def test_one_bad_row_rejects_the_whole_feed(db):
    data = fixtureJson('protons')
    data[-1]['flux'] = 'N/A'
    isw.runIngestion(db, fetcher({'protons': json.dumps(data)}), isw.JOB_FAST)
    assert count(db, where="series LIKE 'goesProton%'") == 0


def test_html_instead_of_json_is_rejected(db):
    changes, failed, note = isw.runIngestion(db, fetcher({'scales': '<html>maintenance</html>'}), isw.JOB_FAST)
    assert failed and 'not JSON' in note
    assert count(db, where="series LIKE 'noaaScale%'") == 0


def test_main_records_a_failed_run(tmp_path, monkeypatch):
    path = str(tmp_path / 'ingestionSWPC.db')
    monkeypatch.setattr(isw, 'openDb', lambda: isw.connect(path))
    monkeypatch.setattr(isw, 'PacedFetcher', lambda: fetcher({'scales': '[]'}))
    assert isw.main(['--job', 'swpcFast']) == 1
    run = sqlite3.connect(path).execute('SELECT job, succeeded, changes, note FROM ingestionRuns').fetchone()
    assert run[:2] == ('swpcFast', 0) and run[2] > 0 and 'scales: FeedError' in run[3]


def test_main_records_a_good_run(tmp_path, monkeypatch):
    path = str(tmp_path / 'ingestionSWPC.db')
    monkeypatch.setattr(isw, 'openDb', lambda: isw.connect(path))
    monkeypatch.setattr(isw, 'PacedFetcher', lambda: fetcher())
    assert isw.main(['--job', 'swpcSlow']) == 0
    run = sqlite3.connect(path).execute('SELECT job, succeeded, changes FROM ingestionRuns').fetchone()
    assert run[:2] == ('swpcSlow', 1) and run[2] > 0


def test_prune_job_deletes_old_minutes_and_records_the_rows_as_changes(tmp_path, monkeypatch):
    path = str(tmp_path / 'ingestionSWPC.db')
    conn = isw.connect(path)
    isw.runIngestion(conn, fetcher(), isw.JOB_SLOW)   # fixtures are from 2026-10-24: inside any window then
    before = count(conn, where="series LIKE 'l1%'")
    conn.close()
    monkeypatch.setattr(isw, 'openDb', lambda: isw.connect(path))
    monkeypatch.setattr(isw, 'datetime', type('D', (), {'utcnow': staticmethod(lambda: datetime(2027, 3, 1))}))
    assert isw.main(['--job', 'swpcPrune']) == 0
    conn = sqlite3.connect(path)
    run = conn.execute('SELECT job, succeeded, changes FROM ingestionRuns').fetchone()
    assert run[:2] == ('swpcPrune', 1) and run[2] == before > 0
    assert conn.execute("SELECT COUNT(*) FROM samples WHERE series LIKE 'l1%'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM samples WHERE series = 'swpcKp'").fetchone()[0] > 0


def test_every_job_covers_its_feeds_and_together_every_feed_once():
    fast, slow, maps = isw.JOBS[isw.JOB_FAST], isw.JOBS[isw.JOB_SLOW], isw.JOBS[isw.JOB_MAPS]
    assert sorted(fast + slow + maps) == sorted(isw.FEEDS)
    assert 'ovation' not in slow and 'drap' not in slow   # swpcSlow is unchanged


# --- swpcMaps feeds ---------------------------------------------------------------

def synthetic(fill=0, cells=()):
    """An OVATION response, every cell `fill`, with `cells` ((lon, lat): value) set."""
    values = {(lon, lat): fill for lon in range(360) for lat in range(-90, 91)}
    values.update(dict(cells))
    return json.dumps({'Observation Time': '2026-10-24T16:25:00Z', 'Forecast Time': '2026-10-24T17:32:00Z',
                       'Data Format': '[Longitude, Latitude, Aurora]',
                       'coordinates': [[lon, lat, v] for (lon, lat), v in values.items()]})


def test_ovation_gives_per_hemisphere_summaries_stamped_at_the_forecast_time_and_the_whole_global_map():
    samples, events, maps = isw.parseOvation(fixtureText('ovation'))
    byName = {s[0]: s for s in samples}
    assert events == [] and sorted(byName) == sorted(
        f'ovation{what}{h}{tail}' for h in 'NS' for what, tail in (('Max', ''), ('Max', 'Lat'), ('Max', 'Lon'), ('Edge', ''),
                                                                   ('Edge', 'Lon'), ('Edge', 'Cover'), ('Edge', 'Faint'),
                                                                   ('Edge', 'FaintLon'), ('Edge', 'FaintCover')))
    # the map predicts the aurora at the FORECAST time (17:32): that is the stamp; the observation time is in the quality
    assert all(s[1] == '2026-10-24T17:32:00Z' and s[4] == 'observed 2026-10-24T16:25:00Z' for s in samples)
    cells = {(c[0], c[1]): c[2] for c in fixtureJson('ovation')['coordinates']}
    assert byName['ovationMaxN'][2] == max(v for (lon, lat), v in cells.items() if lat > 0)
    assert byName['ovationMaxS'][2] == max(v for (lon, lat), v in cells.items() if lat < 0)
    for h in 'NS':   # where the maximum is: the cell holds that value, in the right hemisphere
        lat, lon = byName[f'ovationMax{h}Lat'][2], byName[f'ovationMax{h}Lon'][2]
        assert (lat > 0) == (h == 'N') and -180 <= lon < 180
        assert cells[(int(lon) % 360, int(lat))] == byName[f'ovationMax{h}'][2]
    name, ts, record = maps[0]
    assert name == 'ovation' and ts == '2026-10-24T17:32:00Z'
    assert record['obs'] == '2026-10-24T16:25:00Z' and record['forecast'] == '2026-10-24T17:32:00Z'
    assert record['latMin'] == -90 and len(record['rows']) == 181 and all(len(r) == 360 for r in record['rows'])
    assert record['rows'][64 + 90][338] == int(cells[(338, 64)]) and record['rows'][-53 + 90][96] == int(cells[(96, -53)])
    assert len(record['edgeN']) == len(record['edgeS']) == len(record['edgeFaintN']) == len(record['edgeFaintS']) == 360


def test_oval_edge_matches_spocks_unit_test_values_on_the_two_maps():
    # (map, hemisphere) -> (reach, centre longitude of the longest run at the reach, cover)
    with open(os.path.join(TESTS_DIR, 'fixtures', 'swpcOvationMap1857.json')) as f:
        rows1857 = json.load(f)['rows']
    rows1625 = isw.parseOvation(fixtureText('ovation'))[2][0][2]['rows']
    expected = {('1857', 1): (64.0, 63.0, 161), ('1857', -1): (50.0, 97.0, 190),
                ('1625', 1): (64.0, 95.0, 210), ('1625', -1): (48.0, 110.0, 134)}
    for (which, sign), (reach, lon, cover) in expected.items():
        sm, got, gotLon, gotCover = isw.ovalEdges(rows1857 if which == '1857' else rows1625, sign)
        assert (got, gotLon, gotCover) == (reach, lon, cover), (which, sign)
        assert len(sm) == 360 and min(x for x in sm if x is not None) == reach and sum(x is not None for x in sm) == cover


def synthetic_rows(fill=0, cells=()):
    rows = [[fill] * 360 for _ in range(181)]
    for (lon, lat), value in cells:
        rows[lat + 90][lon] = value
    return rows


def test_oval_edge_scans_from_the_equator_needs_two_cells_and_ignores_the_pole_rows():
    ring = [((lon, lat), 15) for lon in range(360) for lat in (62, 63)]          # a north oval at 62 N and 63 N all round
    ring += [((lon, -89), 50) for lon in range(360)] + [((lon, -90), 50) for lon in range(360)]   # south: only the pole rows
    ring += [((lon, 40), 12) for lon in range(100, 110)]                          # a single cell thick: no run of two
    sm, reach, lon, cover = isw.ovalEdges(synthetic_rows(0, ring), 1)
    assert (reach, cover) == (62.0, 360) and all(x == 62 for x in sm)
    assert isw.ovalEdges(synthetic_rows(0, ring), -1) == ([None] * 360, None, None, 0)    # pole rows never count


def test_oval_edge_needs_10_longitudes_and_smooths_by_the_median_of_five():
    assert isw.OVAL_MIN_LONS == 10                                                       # was 30: it hid real narrow midnight patches
    narrow = [((lon, 70), 20) for lon in range(0, 12)] + [((lon, 71), 20) for lon in range(0, 12)]
    assert isw.ovalEdges(synthetic_rows(0, narrow), 1)[1:] == (70.0, 6.0, 12)           # 12 longitudes at 70 N now count (centre of 0..11)
    thin = [((lon, 55), 20) for lon in range(0, 9)] + [((lon, 56), 20) for lon in range(0, 9)]
    assert isw.ovalEdges(synthetic_rows(0, thin), 1)[1:] == (None, None, 9)             # 9 longitudes: one short
    wide = [((lon, 55), 20) for lon in range(0, 40)] + [((lon, 56), 20) for lon in range(0, 40)]
    sm, reach, lon, cover = isw.ovalEdges(synthetic_rows(0, wide), 1)
    assert (reach, cover) == (55.0, 40) and lon == 20.0                                    # centre of lon 0..39
    # one spike deeper than its neighbours is smoothed away by the median of five
    spike = wide + [((10, 40), 20), ((10, 41), 20)]
    assert isw.ovalEdges(synthetic_rows(0, spike), 1)[1] == 55.0


def test_oval_edge_longest_run_wraps_across_longitude_zero_and_longitudes_are_west_negative():
    cells = [((lon % 360, lat), 20) for lon in range(340, 380) for lat in (50, 51)]        # 340..359 and 0..19: 40 wide
    sm, reach, lon, cover = isw.ovalEdges(synthetic_rows(0, cells), 1)
    assert reach == 50.0 and lon == 0.0 and cover == 40                                       # 340..359 and 0..19: the centre is 0 E
    cells = [((lon, lat), 20) for lon in range(200, 240) for lat in (50, 51)]
    assert isw.ovalEdges(synthetic_rows(0, cells), 1)[2] == -140.0                         # the centre, 220 E, is 140 W


def test_the_faint_tier_is_the_same_algorithm_at_index_5_and_lies_equatorward_of_the_naked_eye_edge():
    samples, _, maps = isw.parseOvation(fixtureText('ovation'))
    byName = {s[0]: s[2] for s in samples}
    assert 61 <= byName['ovationEdgeNFaint'] <= 62 and 46 <= byName['ovationEdgeSFaint'] <= 47      # Spock: N 61-62, S 46-47 degrees
    assert byName['ovationEdgeNFaint'] < byName['ovationEdgeN'] and byName['ovationEdgeSFaint'] < byName['ovationEdgeS']
    assert byName['ovationEdgeNFaintCover'] >= byName['ovationEdgeNCover']
    sm, reach, lon, cover = isw.ovalEdges(maps[0][2]['rows'], 1, isw.OVAL_T_FAINT)
    assert (reach, lon, cover) == (byName['ovationEdgeNFaint'], byName['ovationEdgeNFaintLon'], byName['ovationEdgeNFaintCover'])
    assert maps[0][2]['edgeFaintN'] == sm


def test_when_no_edge_exists_the_peak_and_where_it_is_are_still_stored_for_the_no_visible_aurora_line():
    cells = [((100, 70), 8), ((101, 70), 7), ((100, -60), 6)]               # faint: below 10 everywhere, 5 or more in a few cells
    samples, _, _ = isw.parseOvation(synthetic(0, cells))
    byName = {s[0]: s[2] for s in samples}
    assert byName['ovationEdgeN'] is None and byName['ovationEdgeNFaint'] is None                  # fewer than 10 longitudes
    assert (byName['ovationMaxN'], byName['ovationMaxNLat'], byName['ovationMaxNLon']) == (8.0, 70.0, 100.0)
    assert (byName['ovationMaxS'], byName['ovationMaxSLat'], byName['ovationMaxSLon']) == (6.0, -60.0, 100.0)


def test_f107_anchor_is_the_median_of_the_days_readings_so_a_noon_burst_flags_noon_only():
    def day(date, morning, noon, afternoon):
        return [{'time_tag': f'2026-{date}T{h}:00:00', 'flux': v, 'reporting_schedule': q, 'ninety_day_mean': None}
                for h, q, v in (('17', 'Morning', morning), ('20', 'Noon', noon), ('22', 'Afternoon', afternoon))]
    # 1 July: Noon is the burst (249.7); a Noon anchor would have flagged the two clean readings instead
    rows, _ = isw.parseF107(json.dumps(day('07-01', 200.0, 249.7, 203.0)))
    assert {r[1][11:13]: r[4] for r in rows if r[0] == 'swpcF107'} == {'17': 'Morning', '20': 'Noon burst?', '22': 'Afternoon'}
    # 13 October: the afternoon is the burst
    rows, _ = isw.parseF107(json.dumps(day('10-13', 124.0, 136.0, 207.0)))
    assert {r[1][11:13]: r[4] for r in rows if r[0] == 'swpcF107'} == {'17': 'Morning', '20': 'Noon', '22': 'Afternoon burst?'}
    # fewer than three readings: no flag
    rows, _ = isw.parseF107(json.dumps(day('10-14', 124.0, 136.0, 207.0)[:2]))
    assert {r[4] for r in rows if r[0] == 'swpcF107'} == {'Morning', 'Noon'}


def test_a_quiet_ovation_gives_no_edge_but_still_a_cover_of_zero_and_a_maximum_somewhere():
    samples, _, maps = isw.parseOvation(synthetic(0))
    byName = {s[0]: s[2] for s in samples}
    assert byName['ovationEdgeN'] is None and byName['ovationEdgeS'] is None and byName['ovationEdgeNLon'] is None
    assert byName['ovationEdgeNCover'] == 0.0 and byName['ovationMaxN'] == 0.0
    assert maps[0][2]['edgeN'] == [None] * 360


def test_ovation_with_a_missing_cell_is_rejected():
    data = fixtureJson('ovation')
    data['coordinates'].pop(100)
    with pytest.raises(FeedError, match='incomplete'):
        isw.parseOvation(json.dumps(data))


def test_ovation_with_a_value_out_of_range_is_rejected():
    data = fixtureJson('ovation')
    data['coordinates'][5][2] = 101
    with pytest.raises(FeedError, match='out of range'):
        isw.parseOvation(json.dumps(data))


@pytest.mark.parametrize('change', [lambda d: d.pop('Forecast Time'), lambda d: d.update(coordinates=[[1, 2]]),
                                    lambda d: d.update(coordinates=[[400, 50, 1]])])
def test_ovation_surprises_are_rejected(change):
    data = fixtureJson('ovation')
    change(data)
    with pytest.raises(FeedError):
        isw.parseOvation(json.dumps(data))


def test_drap_gives_the_global_maximum_and_a_location_nearest_the_subsolar_point():
    samples, events, maps = isw.parseDrap(fixtureText('drap'))
    byName = {s[0]: s for s in samples}
    assert events == [] and sorted(byName) == ['drapMax', 'drapMaxLat', 'drapMaxLon']
    assert byName['drapMax'][1] == '2026-10-24T16:30:00Z' and byName['drapMax'][3] == 'MHz'
    assert 'Normal X-ray Background' in byName['drapMax'][4]
    record = maps[0][2]
    assert maps[0][0] == 'drapGlobal' and len(record['tenths']) == 90 and all(len(r) == 90 for r in record['tenths'])
    assert byName['drapMax'][2] == max(max(r) for r in record['tenths']) / 10
    row, col = (89 - int(byName['drapMaxLat'][2])) // 2, (int(byName['drapMaxLon'][2]) + 178) // 4
    assert record['tenths'][row][col] / 10 == byName['drapMax'][2]
    # Spock: on 24 Oct 16:30 the subsolar point is near 12 S, 72 W (the old code reported the first tied cell in table order)
    sunLat, sunLon = isw.subsolarPoint(datetime(2026, 10, 24, 16, 30))
    assert sunLat == pytest.approx(-11.8, abs=0.6) and sunLon == pytest.approx(-71.5, abs=1.0)
    assert abs(byName['drapMaxLat'][2] - sunLat) < 14 and abs(byName['drapMaxLon'][2] - sunLon) < 10


def test_subsolar_point_at_the_other_known_moment():
    lat, lon = isw.subsolarPoint(datetime(2026, 10, 24, 19, 8))
    assert lat == pytest.approx(-12.0, abs=0.6) and lon == pytest.approx(-111.0, abs=1.0)      # Spock's figures
    assert isw.subsolarPoint(datetime(2026, 6, 21, 12, 0))[0] == pytest.approx(23.4, abs=0.5)


def test_drap_ties_are_broken_towards_the_subsolar_point_not_by_table_order():
    text = fixtureText('drap')
    lines = text.splitlines()
    out = []
    for line in lines:
        found = re.match(r'^(\s*-?\d+ )\|', line)
        out.append(found.group(1) + '|' + ' 0.5' * 90 if found else line)
    flat = chr(10).join(out)
    samples, _, _ = isw.parseDrap(flat)
    byName = {s[0]: s[2] for s in samples}
    sunLat, sunLon = isw.subsolarPoint(datetime(2026, 10, 24, 16, 30))
    assert byName['drapMax'] == 0.5
    assert abs(byName['drapMaxLat'] - sunLat) <= 1.5 and abs(byName['drapMaxLon'] - sunLon) <= 3.0      # all 8,100 cells tie


@pytest.mark.parametrize('damage', [lambda t: t.replace('Product Valid At', 'Product Was At'),
                                    lambda t: t.replace('-178 -174', '-178 -170', 1),
                                    lambda t: chr(10).join(t.splitlines()[:-1]),
                                    lambda t: t.replace(' 0.3 ', ' N/A ', 1)])
def test_drap_surprises_are_rejected(damage):
    with pytest.raises(FeedError):
        isw.parseDrap(damage(fixtureText('drap')))


def test_maps_job_stores_summaries_and_maps_and_a_repeat_changes_nothing(db):
    changes, failed, note = isw.runIngestion(db, fetcher(), isw.JOB_MAPS)
    assert not failed and changes == 23   # 18 + 3 samples, 2 maps
    assert {r[0] for r in db.execute('SELECT name FROM latestMaps')} == {'ovation', 'drapGlobal'}
    assert isw.runIngestion(db, fetcher(), isw.JOB_MAPS)[0] == 0


def test_a_newer_map_replaces_the_older_and_an_older_one_is_ignored(db):
    isw.runIngestion(db, fetcher(), isw.JOB_MAPS)
    data = fixtureJson('ovation')
    data['Forecast Time'] = '2026-10-24T17:40:00Z'
    assert isw.runIngestion(db, fetcher({'ovation': json.dumps(data)}), isw.JOB_MAPS)[0] == 19   # 18 samples, 1 map
    assert db.execute("SELECT tsUtc FROM latestMaps WHERE name = 'ovation'").fetchone()[0] == '2026-10-24T17:40:00Z'
    assert isw.runIngestion(db, fetcher(), isw.JOB_MAPS)[0] == 0   # the older map (and its samples, already held) change nothing
    assert db.execute("SELECT tsUtc FROM latestMaps WHERE name = 'ovation'").fetchone()[0] == '2026-10-24T17:40:00Z'
