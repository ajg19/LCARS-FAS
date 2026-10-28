"""Tests for scripts/ingestionGFZ.py -- against a temporary database and
GFZ responses recorded on 2026-10-24 and trimmed (0_tests/fixtures/,
gfz*); nothing touches the network or the real databases/ingestionGFZ.db."""

import json
import os
import sqlite3
import sys
from datetime import datetime

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(TESTS_DIR), 'scripts'))
import ingestionGFZ as igfz  # noqa: E402
from spaceWeatherSamples import FeedError  # noqa: E402

NOW = datetime(2026, 10, 24, 15, 20)   # the recording time: the 15:00-18:00 Kp slot has begun but has no value yet


def fixtureText(name):
    with open(os.path.join(TESTS_DIR, 'fixtures', name), encoding='utf-8') as f:
        return f.read()


API_FIXTURES = {'Kp': 'gfzKp.json', 'ap': 'gfzKp.json', 'Ap': 'gfzAp.json', 'SN': 'gfzSN.json', 'Fobs': 'gfzFobs.json',
                'Fadj': 'gfzFobs.json', 'Hp30': 'gfzHp30.json', 'Hp60': 'gfzHp60.json'}


def fetcher(replace=None, fail=(), seen=None):
    """A fetch() stand-in. The nowcast URL answers with the nowcast fixture, an API URL with the fixture for its
    index (ap and Fadj reuse the Kp and Fobs shapes under their own key), unless `replace` / `fail` say otherwise."""
    replace = replace or {}

    def fetch(url):
        if seen is not None:
            seen.append(url)
        name = 'nowcast' if url == igfz.NOWCAST_URL else url.rsplit('index=', 1)[1]
        if name in fail:
            raise Exception('HTTP 503')
        if name in replace:
            return replace[name]
        if name == 'nowcast':
            return fixtureText('gfzNowcast.txt')
        data = json.loads(fixtureText(API_FIXTURES[name]))
        for stock, own in (('Kp', 'ap'), ('Fobs', 'Fadj')):
            if name == own:
                data[own] = data.pop(stock)
        return json.dumps(data)
    return fetch


@pytest.fixture
def db(tmp_path):
    conn = igfz.openDb(str(tmp_path / 'ingestionGFZ.db'))
    yield conn
    conn.close()


def series(rows, name):
    return {r[1]: r[2] for r in rows if r[0] == name}


def stored(db, name):
    return {r[0]: r[1:] for r in db.execute('SELECT tsUtc, value, unit, quality FROM samples WHERE series = ?', (name,))}


# --- Nowcast file -----------------------------------------------------------------

def test_nowcast_gives_eight_kp_and_ap_a_day_and_the_daily_values():
    rows = igfz.parseNowcast(fixtureText('gfzNowcast.txt'), NOW)
    kp = series(rows, 'gfzKp')
    assert kp['2026-09-25T00:00:00Z'] == 3.667 and kp['2026-09-25T21:00:00Z'] == 4.0
    assert series(rows, 'gfzAp3h')['2026-10-23T18:00:00Z'] == 32.0
    assert series(rows, 'gfzAp')['2026-10-23T00:00:00Z'] == 11.0
    assert series(rows, 'gfzSunspotNumber')['2026-09-25T00:00:00Z'] == 89.0
    assert series(rows, 'gfzF107Obs')['2026-09-25T00:00:00Z'] == 105.4
    assert series(rows, 'gfzF107Adj')['2026-09-25T00:00:00Z'] == 106.0
    assert {r[3] for r in rows if r[0] == 'gfzF107Obs'} == {'sfu'}


def test_nowcast_quality_follows_the_d_flag():
    rows = igfz.parseNowcast(fixtureText('gfzNowcast.txt'), NOW)
    quality = {(r[0], r[1][:10]): r[4] for r in rows}
    assert quality[('gfzKp', '2026-09-25')] == 'def' and quality[('gfzSunspotNumber', '2026-09-25')] == 'pre'   # D = 1
    assert quality[('gfzKp', '2026-10-23')] == 'pre' and quality[('gfzAp', '2026-10-23')] == 'pre'            # D = 0
    both = fixtureText('gfzNowcast.txt').replace('106.0 1', '106.0 2')
    assert {r[0]: r[4] for r in igfz.parseNowcast(both, NOW) if r[1] == '2026-09-25T00:00:00Z'}['gfzSunspotNumber'] == 'def'


def test_a_missing_value_in_a_slot_that_has_begun_is_null_and_a_future_slot_has_no_row():
    rows = igfz.parseNowcast(fixtureText('gfzNowcast.txt'), NOW)
    kp = series(rows, 'gfzKp')
    assert kp['2026-10-24T12:00:00Z'] == 1.0
    assert kp['2026-10-24T15:00:00Z'] is None            # begun at 15:00, no value yet
    assert '2026-10-24T18:00:00Z' not in kp and '2026-10-24T21:00:00Z' not in kp
    assert series(rows, 'gfzF107Obs')['2026-10-24T00:00:00Z'] is None   # -1.0 for today's noon flux so far
    assert series(rows, 'gfzAp')['2026-10-24T00:00:00Z'] is None


def test_no_minus_one_ever_reaches_the_database():
    rows = igfz.parseNowcast(fixtureText('gfzNowcast.txt'), NOW)
    assert all(r[2] is None or r[2] >= 0 for r in rows)


@pytest.mark.parametrize('damage', [lambda t: t.replace('geomagnetic planetary three-hour index Kp', 'something else'),
                                    lambda t: t + '2026 10 25 not a data line\n',
                                    lambda t: t.replace('106.0 1', '106.0 7'),
                                    lambda t: ''.join(l for l in t.splitlines(True) if l.startswith('#'))])
def test_a_nowcast_with_a_surprise_is_rejected(damage):
    with pytest.raises(FeedError):
        igfz.parseNowcast(damage(fixtureText('gfzNowcast.txt')), NOW)


# --- JSON API ---------------------------------------------------------------------

def test_api_kp_with_status():
    rows = igfz.parseApi(fixtureText('gfzKp.json'), 'Kp', NOW)
    assert len(rows) == 6 and rows[0] == ('gfzKp', '2026-10-22T00:00:00Z', 2.667, 'Kp', 'pre')


def test_api_status_key_is_prefixed_for_sunspot_number_and_daily_ap():
    assert {r[4] for r in igfz.parseApi(fixtureText('gfzSN.json'), 'SN', NOW)} == {'pre'}
    assert {r[4] for r in igfz.parseApi(fixtureText('gfzAp.json'), 'Ap', NOW)} == {'pre'}


def test_api_hp30_has_no_status_and_starts_each_interval_at_its_start():
    rows = igfz.parseApi(fixtureText('gfzHp30.json'), 'Hp30', NOW)
    assert len(rows) == 8 and {r[4] for r in rows} == {None} and {r[3] for r in rows} == {'Hp'}
    assert [r[1] for r in rows[:3]] == ['2026-10-22T00:00:00Z', '2026-10-22T00:30:00Z', '2026-10-22T01:00:00Z']


def test_api_f107_is_observed_and_adjusted():
    assert igfz.parseApi(fixtureText('gfzFobs.json'), 'Fobs', NOW)[0] == ('gfzF107Obs', '2026-10-22T00:00:00Z', 106.5, 'sfu', None)


def test_api_minus_one_is_null():
    data = json.loads(fixtureText('gfzSN.json'))
    data['SN'][1] = -1
    assert igfz.parseApi(json.dumps(data), 'SN', NOW)[1][2] is None


@pytest.mark.parametrize('damage', [lambda d: d.pop('datetime'),
                                    lambda d: d.update(Kp=d['Kp'][:-1]),
                                    lambda d: d.update(status=['final'] * 6),
                                    lambda d: d.update(Kp=['high'] * 6),
                                    lambda d: d.update(status=d['status'][:2])])
def test_an_api_response_with_a_surprise_is_rejected(damage):
    data = json.loads(fixtureText('gfzKp.json'))
    damage(data)
    with pytest.raises(FeedError):
        igfz.parseApi(json.dumps(data), 'Kp', NOW)


def test_api_urls_are_chunked_by_year():
    urls = igfz.apiUrls('Kp', datetime(2020, 1, 1), datetime(2022, 1, 1))
    assert len(urls) == 2 and urls[0].startswith(
        'https://kp.gfz.de/app/json/?start=2020-01-01T00:00:00Z&end=2021-01-01T00:00:00Z&index=Kp')
    assert len(igfz.apiUrls('Kp', datetime(2026, 10, 21, 15), datetime(2026, 10, 24, 15))) == 1


# --- Run ----------------------------------------------------------------------

def test_run_reads_the_nowcast_and_hp_and_a_repeat_changes_nothing(db):
    seen = []
    changes, failed, note = igfz.runIngestion(db, fetcher(seen=seen), now=NOW)
    assert not failed and changes > 0 and note.startswith('nowcast ')
    assert [u.rsplit('index=', 1)[-1] if 'index=' in u else 'nowcast' for u in seen] == ['nowcast', 'Hp30', 'Hp60']
    assert '&end=2026-10-24T15:00:00Z' in seen[1] and 'start=2026-10-21T15:00:00Z' in seen[1]
    assert set(stored(db, 'gfzHp30')) >= {'2026-10-22T00:00:00Z'}
    assert igfz.runIngestion(db, fetcher(), now=NOW)[0] == 0


def test_backfill_reads_every_index_after_the_usual_requests(db):
    seen = []
    changes, failed, _ = igfz.runIngestion(db, fetcher(seen=seen), backfillDays=30, now=NOW)
    assert not failed
    assert [u.rsplit('index=', 1)[1] for u in seen[3:]] == list(igfz.INDEXES)
    assert 'start=2026-09-24T15:00:00Z' in seen[3]
    # the API comes last, so its sunspot number (38) stands over the nowcast's (39) for 23 Oct
    assert stored(db, 'gfzSunspotNumber')['2026-10-23T00:00:00Z'][0] == 38.0


def test_a_definitive_value_survives_a_later_preliminary_one(db):
    igfz.runIngestion(db, fetcher(), now=NOW)
    assert stored(db, 'gfzKp')['2026-09-25T00:00:00Z'][2] == 'def'
    older = fixtureText('gfzNowcast.txt').replace('3.667  3.333  3.667', '1.000  1.000  1.000')
    igfz.runIngestion(db, fetcher({'nowcast': older.replace('106.0 1', '106.0 0')}), now=NOW)   # D back to preliminary
    assert stored(db, 'gfzKp')['2026-09-25T00:00:00Z'] == (3.667, 'Kp', 'def')


def test_a_preliminary_value_is_replaced_by_the_definitive_one(db):
    igfz.runIngestion(db, fetcher(), now=NOW)
    final = fixtureText('gfzNowcast.txt').replace('2.000  2.000  2.000  2.667', '2.333  2.000  2.000  2.667') \
        .replace('  39 ', '  41 ')
    changes, _, _ = igfz.runIngestion(db, fetcher({'nowcast': final}), now=NOW)
    assert changes >= 2
    assert stored(db, 'gfzKp')['2026-10-23T03:00:00Z'][0] == 2.333
    assert stored(db, 'gfzSunspotNumber')['2026-10-23T00:00:00Z'][0] == 41.0


def test_a_surprise_shape_stores_nothing_from_that_feed_and_fails_the_run(db):
    changes, failed, note = igfz.runIngestion(db, fetcher({'nowcast': '<html>moved</html>'}), now=NOW)
    assert failed and 'nowcast: FeedError' in note
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series IN ('gfzKp', 'gfzAp', 'gfzF107Obs')").fetchone()[0] == 0
    assert changes > 0 and stored(db, 'gfzHp30')   # Hp30 and Hp60 are separate requests


def test_a_half_good_api_response_stores_nothing(db):
    data = json.loads(fixtureText('gfzHp30.json'))
    data['Hp30'][-1] = 'n/a'
    changes, failed, _ = igfz.runIngestion(db, fetcher({'Hp30': json.dumps(data)}), now=NOW)
    assert failed and not stored(db, 'gfzHp30')


def test_an_unreachable_feed_fails_the_run_and_keeps_what_we_hold(db):
    igfz.runIngestion(db, fetcher(), now=NOW)
    before = db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
    changes, failed, note = igfz.runIngestion(db, fetcher(fail=('nowcast', 'Hp60')), now=NOW)
    assert failed and changes == 0 and 'nowcast: Exception: HTTP 503' in note and 'Hp60: Exception' in note
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == before


def test_main_records_a_failed_run(tmp_path, monkeypatch):
    path = str(tmp_path / 'ingestionGFZ.db')
    monkeypatch.setattr(igfz, 'openDb', lambda: igfz.connect(path))
    monkeypatch.setattr(igfz, 'PacedFetcher', lambda: fetcher(fail=('Hp30',)))
    assert igfz.main([]) == 1
    run = sqlite3.connect(path).execute('SELECT job, succeeded, note FROM ingestionRuns').fetchone()
    assert run[:2] == ('gfz', 0) and 'Hp30: Exception: HTTP 503' in run[2]
