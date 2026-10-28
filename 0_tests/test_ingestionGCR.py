"""Tests for scripts/ingestionGCR.py -- against a temporary database and Oulu
cosmic ray station responses recorded on 2026-10-24 (0_tests/fixtures/nmdb*);
nothing touches the network or the real databases/ingestionGCR.db."""

import os
import sqlite3
import sys
from datetime import datetime

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(TESTS_DIR), 'scripts'))
import ingestionGCR as gcr  # noqa: E402
from spaceWeatherSamples import FeedError  # noqa: E402

NOW = datetime(2026, 10, 24, 19, 30)


def fixture(name):
    with open(os.path.join(TESTS_DIR, 'fixtures', name), encoding='utf-8') as f:
        return f.read()


def fakeFetch(answers):
    """fetch(url): the answer for the station and resolution named in the URL; records the URLs."""
    seen = []

    def fetch(url):
        seen.append(url)
        station = 'DOMC' if 'station=DOMC' in url else 'OULU'
        kind = 'monthly' if 'resolution=44640' in url else 'hourly'
        return answers[(station, kind)]
    fetch.seen = seen
    return fetch


ANSWERS = {('OULU', 'hourly'): fixture('nmdbOuluHourly30d.csv'), ('DOMC', 'hourly'): fixture('nmdbDomcHourly3d.csv'),
           ('OULU', 'monthly'): fixture('nmdbOuluMonthly1964.csv'), ('DOMC', 'monthly'): fixture('nmdbDomcMonthly.csv')}


@pytest.fixture
def db(tmp_path):
    conn = gcr.openDb(str(tmp_path / 'ingestionGCR.db'))
    yield conn
    conn.close()


def test_hourly_csv_gives_corrected_raw_and_pressure_per_hour():
    rows = gcr.parseCounts(fixture('nmdbOuluHourly30d.csv'), 'OULU', gcr.HOURLY, NOW)
    assert len(rows) == 3 * 738
    first = [r for r in rows if r[1] == '2026-09-24T00:00:00Z']
    assert sorted(first) == sorted([('gcrOuluCorrected', '2026-09-24T00:00:00Z', 6089.0, 'cts/min', 'verified'),
                                    ('gcrOuluRaw', '2026-09-24T00:00:00Z', 5365.0, 'cts/min', 'verified'),
                                    ('gcrOuluPressure', '2026-09-24T00:00:00Z', 1016.86, 'mbar', 'verified')])


def test_the_month_in_progress_is_provisional():
    rows = gcr.parseCounts(fixture('nmdbOuluHourly30d.csv'), 'OULU', gcr.HOURLY, NOW)
    assert {r[4] for r in rows if r[1] < '2026-10-01'} == {'verified'}
    assert {r[4] for r in rows if r[1] >= '2026-10-01'} == {'provisional'}


def test_monthly_series_have_their_own_names():
    rows = gcr.parseCounts(fixture('nmdbOuluMonthly1964.csv'), 'OULU', gcr.MONTHLY, NOW)
    assert {r[0] for r in rows} == {'gcrOuluMonthlyCorrected', 'gcrOuluMonthlyRaw', 'gcrOuluMonthlyPressure'}
    assert rows[0][1] == '1964-04-01T00:00:00Z'


def test_dome_c_has_its_own_prefix_and_pressure_range():
    rows = gcr.parseCounts(fixture('nmdbDomcHourly3d.csv'), 'DOMC', gcr.HOURLY, NOW)
    assert {r[0] for r in rows} == {'gcrDomcCorrected', 'gcrDomcRaw', 'gcrDomcPressure'}
    assert min(r[2] for r in rows if r[0] == 'gcrDomcPressure') < 650     # Dome C sits at about 640 mbar


def test_dome_c_monthly_record_starts_in_2016_and_a_split_january_is_one_partial_month():
    rows = gcr.parseCounts(fixture('nmdbDomcMonthly.csv'), 'DOMC', gcr.MONTHLY, NOW)
    corrected = {r[1]: r[2] for r in rows if r[0] == 'gcrDomcMonthlyCorrected'}
    assert len(corrected) == 127 and min(corrected) == '2016-03-01T00:00:00Z'
    # the server sent 2026-01-01 as all zeros (1-8 January empty) and 2026-01-09 with the data (882 corrected): one row, the 1st
    assert corrected['2026-01-01T00:00:00Z'] == 882.0 and '2026-01-09T00:00:00Z' not in corrected
    quality = {r[4] for r in rows if r[1] == '2026-01-01T00:00:00Z'}
    assert quality == {'verified; partial month from 2026-01-09'}
    assert all(v > 500 for v in corrected.values())


def test_a_month_of_only_zeros_stays_null_and_hourly_zero_rows_are_null():
    text = 'Timestamp,FractionalDate,UncorrectedCountRate[cts/min],CorrectedCountRate[cts/min],Pressure[mbar]' + chr(10)
    monthly = text + '2025-12-01T00:00:00Z,2025.9,0,0,0.00 ' + chr(10) + '2026-01-01T00:00:00Z,2026.0,1000,900,640.00 '
    rows = gcr.parseCounts(monthly, 'DOMC', gcr.MONTHLY, NOW)
    corrected = {r[1]: r[2] for r in rows if r[0] == 'gcrDomcMonthlyCorrected'}
    assert corrected == {'2025-12-01T00:00:00Z': None, '2026-01-01T00:00:00Z': 900.0}
    hourly = text + '2026-10-01T00:00:00Z,1.0,0,0,0.00 ' + chr(10) + '2026-10-01T01:00:00Z,1.1,1000,900,640.00 '
    corrected = {r[1]: r[2] for r in gcr.parseCounts(hourly, 'DOMC', gcr.HOURLY, NOW) if r[0] == 'gcrDomcCorrected'}
    assert corrected == {'2026-10-01T00:00:00Z': None, '2026-10-01T01:00:00Z': 900.0}      # an hourly zero row is not merged


def test_dome_c_months_with_a_heavy_correction_are_marked():
    rows = gcr.parseCounts(fixture('nmdbDomcMonthly.csv'), 'DOMC', gcr.MONTHLY, NOW)
    heavy = sorted(r[1][:7] for r in rows if r[0] == 'gcrDomcMonthlyCorrected' and 'heavily corrected' in r[4])
    assert heavy == ['2016-12', '2017-01', '2017-12', '2018-01', '2018-11', '2018-12', '2019-01', '2019-02']   # Spock: 8 months
    assert not any('heavily' in r[4] for r in gcr.parseCounts(fixture('nmdbOuluMonthly1964.csv'), 'OULU', gcr.MONTHLY, NOW))


def test_reference_levels_for_the_cycle_chart():
    assert gcr.OULU_REFERENCE_CTS_MIN == 6177 and gcr.DOMC_REFERENCE_CTS_MIN == 1081
    assert 100 * (5953 / gcr.OULU_REFERENCE_CTS_MIN - 1) == pytest.approx(-3.6, abs=0.05)      # Spock: Jul 2026 -3.6%


def test_hourly_stamps_are_the_start_of_the_hour_as_documented():
    assert 'START of the averaging hour' in gcr.__doc__ and 'not documented' not in gcr.__doc__


@pytest.mark.parametrize('damage', [
    lambda t: t.replace('Timestamp', 'Time'),
    lambda t: t.replace('2026-09-24T01:00:00Z,267.0416667,5394,6102,1016.40', '2026-09-24T01:00:00Z,267.04,5394,6102'),
    lambda t: t.replace('5394,6102', 'N/A,6102'),
    lambda t: t.replace('5394,6102', '-5,6102'),
    lambda t: t.replace('1016.40', '9999'),
    lambda t: t.replace('2026-09-24T01:00:00Z', 'yesterday', 1),
    lambda t: t.splitlines()[0],
    lambda t: '<html>maintenance</html>'])
def test_surprises_reject_the_whole_response(damage):
    with pytest.raises(FeedError):
        gcr.parseCounts(damage(fixture('nmdbOuluHourly30d.csv')), 'OULU', gcr.HOURLY, NOW)


def test_a_missing_value_is_null_not_zero():
    text = fixture('nmdbOuluHourly30d.csv').replace('5394,6102,1016.40', '5394,,1016.40')
    rows = gcr.parseCounts(text, 'OULU', gcr.HOURLY, NOW)
    assert [r[2] for r in rows if r[0] == 'gcrOuluCorrected' and r[1] == '2026-09-24T01:00:00Z'] == [None]


def test_the_query_url_uses_the_forms_half_hours_and_resolution():
    url = gcr.queryUrl('DOMC', datetime(2026, 10, 21, 0, 0), datetime(2026, 10, 24, 18, 40), 60)
    assert 'station=DOMC' in url and 'starttime=00%3A00' in url and 'endtime=18%3A30' in url
    assert 'startday=21' in url and 'endmonth=10' in url and 'resolution=60' in url and 'outputmode=csv' in url


def test_recent_run_asks_for_three_days_of_each_station_once_and_a_repeat_changes_nothing(db):
    fetch = fakeFetch(ANSWERS)
    changes, failed, note = gcr.runIngestion(db, fetch, now=NOW)
    assert not failed and changes > 0 and len(fetch.seen) == 2
    assert all('startday=21' in u and 'resolution=60' in u for u in fetch.seen)
    assert gcr.runIngestion(db, fakeFetch(ANSWERS), now=NOW)[0] == 0


def test_backfill_splits_a_long_span_into_year_long_requests(db):
    assert len(gcr.plan(NOW, backfillDays=30)) == 2
    assert len(gcr.plan(NOW, backfillDays=400)) == 4          # two stations x two stretches
    assert all(a < b for _, u, _, _ in gcr.plan(NOW, backfillDays=400) for a, b in [(0, 1)])


def test_monthly_run_asks_once_per_station_from_1964(db):
    fetch = fakeFetch(ANSWERS)
    changes, failed, _ = gcr.runIngestion(db, fetch, monthly=True, now=NOW)
    assert not failed and len(fetch.seen) == 2 and all('startyear=1964' in u and 'resolution=44640' in u for u in fetch.seen)
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'gcrOuluMonthlyCorrected'").fetchone()[0] == 750
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'gcrDomcMonthlyCorrected'").fetchone()[0] == 127


def test_a_bad_response_fails_that_request_only(db):
    answers = dict(ANSWERS)
    answers[('DOMC', 'hourly')] = '<html>503</html>'
    changes, failed, note = gcr.runIngestion(db, fakeFetch(answers), now=NOW)
    assert failed and 'DOMC hourly: FeedError' in note and changes > 0
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series LIKE 'gcrDomc%'").fetchone()[0] == 0


def test_main_records_the_right_job(tmp_path, monkeypatch):
    path = str(tmp_path / 'ingestionGCR.db')
    monkeypatch.setattr(gcr, 'openDb', lambda: gcr.connect(path))
    monkeypatch.setattr(gcr, 'PacedFetcher', lambda: fakeFetch(ANSWERS))
    monkeypatch.setattr(gcr, 'utcNow', lambda: NOW)
    assert gcr.main([]) == 0 and gcr.main(['--monthly']) == 0
    jobs = [r[0] for r in sqlite3.connect(path).execute('SELECT job FROM ingestionRuns ORDER BY id')]
    assert jobs == ['gcr', 'gcrMonthly']


def test_the_prune_rule_never_touches_cosmic_ray_series(db):
    import spaceWeatherSamples as sws
    sws.upsertSamples(db, [('gcrOuluCorrected', '2024-01-01T00:00:00Z', 6000.0, 'cts/min', 'verified'),
                           ('gcrOuluMonthlyCorrected', '1964-04-01T00:00:00Z', 6414.0, 'cts/min', 'verified')])
    assert sws.pruneOldOneMinute(db, datetime(2040, 1, 1)) == {}
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 2
