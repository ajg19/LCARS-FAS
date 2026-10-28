"""Tests for scripts/spaceWeatherSamples.py -- the samples and events
tables, the upserts, retention (the 90-day window and the pruning of
old 1-minute rows) and the paced fetcher. Temporary databases; nothing touches
the network."""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import spaceWeatherSamples as sws  # noqa: E402


@pytest.fixture
def db(tmp_path):
    conn = sws.connect(str(tmp_path / 'ingestionTest.db'))
    yield conn
    conn.close()


def row(db, series, ts):
    return db.execute('SELECT value, unit, quality FROM samples WHERE series = ? AND tsUtc = ?', (series, ts)).fetchone()


# --- Samples ------------------------------------------------------------------

def test_upsert_counts_new_rows_and_a_repeat_changes_nothing(db):
    rows = [('swpcKp', '2026-10-24T00:00:00Z', 2.0, 'Kp', 'observed'),
            ('swpcKp', '2026-10-24T03:00:00Z', 1.67, 'Kp', 'estimated')]
    assert sws.upsertSamples(db, rows) == 2
    assert sws.upsertSamples(db, rows) == 0
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 2


def test_upsert_counts_only_the_changed_rows(db):
    sws.upsertSamples(db, [('s', 't1', 1.0, 'u', 'a'), ('s', 't2', 2.0, 'u', 'a')])
    changed = sws.upsertSamples(db, [('s', 't1', 1.0, 'u', 'a'), ('s', 't2', 2.5, 'u', 'a'), ('s', 't3', 3.0, 'u', 'a')])
    assert changed == 2   # t2's value, and the new t3
    assert row(db, 's', 't2') == (2.5, 'u', 'a')


def test_a_missing_reading_is_null_and_a_later_value_replaces_it(db):
    assert sws.upsertSamples(db, [('s', 't1', None, 'nT', 'SOLAR1')]) == 1
    assert row(db, 's', 't1')[0] is None
    assert sws.upsertSamples(db, [('s', 't1', 4.2, 'nT', 'SOLAR1')]) == 1


def test_a_row_repeated_in_one_batch_counts_once_and_the_last_wins(db):
    assert sws.upsertSamples(db, [('s', 't1', 1.0, 'u', None), ('s', 't1', 2.0, 'u', None)]) == 1
    assert sws.upsertSamples(db, [('s', 't1', 1.0, 'u', None), ('s', 't1', 2.0, 'u', None)]) == 0
    assert row(db, 's', 't1')[0] == 2.0


def test_a_definitive_row_is_never_replaced_by_a_preliminary_one(db):
    sws.upsertSamples(db, [('gfzKp', 't1', 3.0, 'Kp', 'def')], finalQuality='def')
    assert sws.upsertSamples(db, [('gfzKp', 't1', 2.67, 'Kp', 'pre')], finalQuality='def') == 0
    assert row(db, 'gfzKp', 't1') == (3.0, 'Kp', 'def')
    # the other way round is the normal course
    sws.upsertSamples(db, [('gfzKp', 't2', 2.0, 'Kp', 'pre')], finalQuality='def')
    assert sws.upsertSamples(db, [('gfzKp', 't2', 2.33, 'Kp', 'def')], finalQuality='def') == 1
    # and without the guard a later row replaces anything
    assert sws.upsertSamples(db, [('gfzKp', 't1', 2.67, 'Kp', 'pre')]) == 1


def test_a_row_without_quality_is_not_blocked_by_the_guard(db):
    sws.upsertSamples(db, [('s', 't1', 1.0, 'sfu', None)], finalQuality='def')
    assert sws.upsertSamples(db, [('s', 't1', 1.5, 'sfu', None)], finalQuality='def') == 1


def test_series_and_time_are_the_key(db):
    sws.upsertSamples(db, [('a', 't1', 1.0, 'u', None), ('b', 't1', 2.0, 'u', None), ('a', 't2', 3.0, 'u', None)])
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 3


# --- Events -------------------------------------------------------------------

def test_events_are_stored_as_json_and_a_repeat_changes_nothing(db):
    rows = [('CME', '2026-10-17T02:48:00Z', 'id-1', {'b': 2, 'a': 1})]
    assert sws.upsertEvents(db, rows) == 1
    assert sws.upsertEvents(db, rows) == 0
    assert db.execute('SELECT json FROM events').fetchone()[0] == '{"a": 1, "b": 2}'


def test_a_revised_event_counts_as_a_change(db):
    sws.upsertEvents(db, [('CME', 't', 'id-1', {'versionId': 1})])
    assert sws.upsertEvents(db, [('CME', 't', 'id-1', {'versionId': 2})]) == 1
    assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1


def test_the_same_id_under_another_type_is_another_event(db):
    sws.upsertEvents(db, [('XRA', 't', 'id-1', {}), ('FLA', 't', 'id-1', {})])
    assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 2


def test_store_feed_adds_both_counts(db):
    assert sws.storeFeed(db, [('s', 't', 1.0, 'u', None)], [('E', 't', 'id', {})]) == 2
    assert sws.storeFeed(db, [('s', 't', 1.0, 'u', None)], [('E', 't', 'id', {})]) == 0


def test_opening_the_tables_twice_is_harmless(db):
    sws.upsertSamples(db, [('s', 't', 1.0, 'u', None)])
    sws.openTables(db)
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 1


# --- Times and numbers ----------------------------------------------------------

@pytest.mark.parametrize('text', ['2026-10-17T02:48Z', '2026-10-17T02:48:00', '2026-10-17T02:48:00Z', '2026-10-17_02:48'])
def test_times_come_out_as_utc_text_with_z(text):
    assert sws.utcText(text) == '2026-10-17T02:48:00Z'


def test_a_bare_date_is_midnight():
    assert sws.utcText('2026-10-24') == '2026-10-24T00:00:00Z'


def test_unreadable_time_is_a_surprise():
    with pytest.raises(sws.FeedError):
        sws.utcText('yesterday')


def test_number_accepts_null_and_numbers_and_rejects_strings_and_booleans():
    assert sws.number(None, 'x') is None
    assert sws.number(3, 'x') == 3.0
    assert sws.number('15', 'x', allowText=True) == 15.0
    assert sws.number('', 'x', allowText=True) is None
    for bad in ('N/A', True, [1]):
        with pytest.raises(sws.FeedError):
            sws.number(bad, 'x')
    with pytest.raises(sws.FeedError):
        sws.number('abc', 'x', allowText=True)


def test_load_json_reports_non_json_as_a_surprise():
    with pytest.raises(sws.FeedError, match='not JSON'):
        sws.loadJson('<html>503</html>')


# --- Retention ----------------------------------------------------------------

def minutes(series, hour, values, unit='nT'):
    return [(series, f'2026-09-01T{hour:02d}:{i:02d}:00Z', v, unit, 'SOLAR1') for i, v in enumerate(values)]


def test_live_window_is_90_days_and_cuts_on_the_hour():
    assert sws.LIVE_DAYS == 90
    assert sws.liveCutoff(datetime(2026, 10, 24, 15, 20)) == '2026-07-26T15:00:00Z'
    assert sws.liveCutoff('2026-10-24T15:20:00Z', days=7) == '2026-10-17T15:00:00Z'


def test_only_the_one_minute_series_are_pruned():
    for name in ('l1MagBt', 'l1WindSpeed', 'goesXrayLong', 'goesXrayShort'):
        assert sws.isOneMinuteSeries(name)
    for name in ('swpcKp', 'swpcKp1m', 'goesProtonGE10MeV', 'hemiPowerNorth', 'swpcDst', 'gfzKp'):
        assert not sws.isOneMinuteSeries(name)


def test_old_minutes_are_deleted_and_nothing_replaces_them(db):
    old = minutes('l1MagBt', 0, [2.0, 4.0]) + minutes('l1MagBt', 1, [None, None])
    recent = [('l1MagBt', '2026-10-20T10:00:00Z', 9.0, 'nT', 'SOLAR1')]
    sws.upsertSamples(db, old + recent)
    assert sws.pruneOldOneMinute(db, datetime(2026, 12, 1, 12, 0)) == {'l1MagBt': 4}
    assert db.execute('SELECT series, tsUtc FROM samples').fetchall() == [('l1MagBt', '2026-10-20T10:00:00Z')]


def test_pruning_stops_at_the_cutoff_hour_so_a_partial_hour_is_kept(db):
    sws.upsertSamples(db, minutes('l1MagBt', 5, [1.0, 2.0, 3.0, 4.0]))
    # cutoff = 2026-09-01T05:00:00Z exactly: rows at 05:00 and later stay
    assert sws.pruneOldOneMinute(db, '2026-11-30T05:02:00Z') == {}
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 4
    assert sws.pruneOldOneMinute(db, '2026-11-30T06:00:00Z') == {'l1MagBt': 4}


def test_a_row_just_inside_the_window_stays(db):
    sws.upsertSamples(db, [('goesXrayLong', '2026-07-26T15:00:00Z', 1e-7, 'W/m2', None),
                           ('goesXrayLong', '2026-07-26T14:59:00Z', 1e-7, 'W/m2', None)])
    assert sws.pruneOldOneMinute(db, datetime(2026, 10, 24, 15, 20)) == {'goesXrayLong': 1}
    assert db.execute('SELECT tsUtc FROM samples').fetchall() == [('2026-07-26T15:00:00Z',)]


def test_pruning_twice_changes_nothing_more(db):
    sws.upsertSamples(db, minutes('goesXrayLong', 0, [1e-7, 3e-7], 'W/m2'))
    assert sws.pruneOldOneMinute(db, datetime(2026, 12, 1)) == {'goesXrayLong': 2}
    assert sws.pruneOldOneMinute(db, datetime(2026, 12, 1)) == {}


def test_prune_leaves_every_other_series_in_full(db):
    sws.upsertSamples(db, minutes('l1MagBt', 0, [2.0, 4.0]) + minutes('l1WindSpeed', 0, [400.0, 410.0], 'km/s')
                      + minutes('swpcKp1m', 0, [1.0, 2.0], 'Kp') + minutes('swpcDst', 0, [-5.0, -6.0])
                      + minutes('goesProtonGE10MeV', 0, [0.1, 0.2], 'pfu'))
    sws.upsertEvents(db, [('CME', '2026-09-01T00:00:00Z', 'id-1', {})])
    assert sws.pruneOldOneMinute(db, datetime(2027, 6, 1)) == {'l1MagBt': 2, 'l1WindSpeed': 2}
    for kept in ('swpcKp1m', 'swpcDst', 'goesProtonGE10MeV'):
        assert db.execute('SELECT COUNT(*) FROM samples WHERE series = ?', (kept,)).fetchone()[0] == 2
    assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1


def test_long_records_survive_a_prune_far_in_the_future(db):
    """Only the L1 and GOES X-ray 1-minute series may ever be deleted: the daily F10.7, Kp, Ap, sunspot
    and Dst series (13 months and more of them) must survive any prune date."""
    kept = ('gfzF107Obs', 'gfzF107Adj', 'swpcF107', 'swpcF107Mean90', 'gfzKp', 'swpcKp', 'gfzAp', 'gfzAp3h', 'gfzHp30',
            'gfzSunspotNumber', 'swpcDst', 'swpcKp1m', 'goesProtonGE10MeV', 'hemiPowerNorth', 'ovationMaxN')
    sws.upsertSamples(db, [(name, '2025-09-20T00:00:00Z', 1.0, 'u', None) for name in kept]
                      + [('l1WindSpeed', '2025-09-20T00:00:00Z', 400.0, 'km/s', None),
                         ('goesXrayLong', '2025-09-20T00:00:00Z', 1e-7, 'W/m2', None)])
    assert sws.pruneOldOneMinute(db, datetime(2026, 10, 24, 20, 0)) == {'l1WindSpeed': 1, 'goesXrayLong': 1}
    assert sws.pruneOldOneMinute(db, datetime(2040, 1, 1)) == {}
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == len(kept)


def test_nothing_inside_the_window_is_pruned(db):
    sws.upsertSamples(db, [('l1MagBt', '2026-10-20T10:00:00Z', 9.0, 'nT', None)])
    assert sws.pruneOldOneMinute(db, datetime(2026, 10, 24, 15, 20)) == {}


# --- Fetcher --------------------------------------------------------------------

def test_fetcher_asks_for_gzip_and_pauses_between_requests_but_not_before_the_first(monkeypatch):
    seen, sleeps = [], []

    def fakeGet(url, headers=None):
        seen.append((url, headers))
        return 200, 'body'

    monkeypatch.setattr(sws, 'httpGet', fakeGet)
    fetch = sws.PacedFetcher(sleep=sleeps.append)
    assert fetch('https://a.test/1') == 'body' and fetch('https://a.test/2') == 'body'
    assert all(h['Accept-Encoding'] == 'gzip' for _, h in seen)
    assert len(sleeps) == 1 and sws.MIN_GAP_SEC <= sleeps[0] <= sws.MAX_GAP_SEC


@pytest.mark.parametrize('reply, message', [((503, 'busy'), 'HTTP 503'), ((200, '  \n'), 'empty response')])
def test_fetcher_raises_on_an_error_or_an_empty_body(monkeypatch, reply, message):
    monkeypatch.setattr(sws, 'httpGet', lambda url, headers=None: reply)
    with pytest.raises(Exception, match=message):
        sws.PacedFetcher(sleep=lambda s: None)('https://a.test/x')
