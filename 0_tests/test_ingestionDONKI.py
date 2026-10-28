"""Tests for scripts/ingestionDONKI.py -- against a temporary database and
DONKI responses recorded on 2026-10-24 and trimmed (0_tests/fixtures/,
donki*); nothing touches the network or the real databases/ingestionDONKI.db."""

import json
import os
import sqlite3
import sys
from datetime import date

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(TESTS_DIR), 'scripts'))
import ingestionDONKI as idk  # noqa: E402
from spaceWeatherSamples import FeedError  # noqa: E402

TODAY = date(2026, 10, 24)


def fixtureText(eventType):
    with open(os.path.join(TESTS_DIR, 'fixtures', f'donki{eventType}.json'), encoding='utf-8') as f:
        return f.read()


def fetcher(replace=None, fail=(), seen=None):
    """A fetch() stand-in: each event type answers with its fixture, unless `replace` / `fail` say otherwise."""
    replace = replace or {}

    def fetch(url):
        if seen is not None:
            seen.append(url)
        eventType = url.split('/get/')[1].split('?')[0]
        if eventType in fail:
            raise Exception('HTTP 503')
        return replace[eventType] if eventType in replace else fixtureText(eventType)
    return fetch


@pytest.fixture
def db(tmp_path):
    conn = idk.openDb(str(tmp_path / 'ingestionDONKI.db'))
    yield conn
    conn.close()


def count(db, eventType=None):
    if eventType:
        return db.execute('SELECT COUNT(*) FROM events WHERE eventType = ?', (eventType,)).fetchone()[0]
    return db.execute('SELECT COUNT(*) FROM events').fetchone()[0]


# --- Parsing ------------------------------------------------------------------

def test_cme_events_keyed_by_activity_id_with_the_whole_record():
    raw = json.loads(fixtureText('CME'))
    events = idk.parseEvents(fixtureText('CME'), 'CME')
    assert [e[0] for e in events] == ['CME', 'CME']
    assert events[0][2] == raw[0]['activityID'] and events[0][1] == idk.utcText(raw[0]['startTime'])
    assert events[0][3]['catalog'] == 'M2M_CATALOG' and 'cmeAnalyses' in events[0][3]


@pytest.mark.parametrize('eventType, idKey, timeKey', [('FLR', 'flrID', 'beginTime'), ('GST', 'gstID', 'startTime'),
                                                       ('HSS', 'hssID', 'eventTime'), ('IPS', 'activityID', 'eventTime')])
def test_each_type_uses_its_own_id_and_time_keys(eventType, idKey, timeKey):
    raw = json.loads(fixtureText(eventType))
    events = idk.parseEvents(fixtureText(eventType), eventType)
    assert len(events) == len(raw)
    assert [e[2] for e in events] == [r[idKey] for r in raw]
    assert events[0][1] == idk.utcText(raw[0][timeKey])
    assert events[0][1].endswith(':00Z')


def test_an_empty_window_is_not_a_surprise():
    assert fixtureText('SEP').strip() == '[]'
    assert idk.parseEvents('[]', 'SEP') == []


def test_sep_events_keyed_by_sep_id_from_a_real_response():
    # donkiSEPevents.json: first 3 of 27 SEP records for 2024-05-01..06-30, recorded 2026-10-24
    with open(os.path.join(TESTS_DIR, 'fixtures', 'donkiSEPevents.json'), encoding='utf-8') as f:
        text = f.read()
    raw = json.loads(text)
    events = idk.parseEvents(text, 'SEP')
    assert [e[2] for e in events] == [r['sepID'] for r in raw]
    assert events[0][1] == '2024-05-09T13:59:00Z' and events[0][3]['versionId'] == 1


def test_a_new_id_key_is_a_surprise():
    raw = json.loads(fixtureText('FLR'))
    for r in raw:
        r['flareID'] = r.pop('flrID')
    with pytest.raises(FeedError, match='flrID'):
        idk.parseEvents(json.dumps(raw), 'FLR')


@pytest.mark.parametrize('text', ['<html>503</html>', '{"error": "moved"}', '[1, 2]', 'null'])
def test_anything_but_a_list_of_objects_is_a_surprise(text):
    with pytest.raises(FeedError):
        idk.parseEvents(text, 'GST')


def test_windows_are_cut_in_30_day_stretches_oldest_first():
    spans = idk.windows(70, TODAY)
    assert [(s.isoformat(), e.isoformat()) for s, e in spans] == [
        ('2026-08-15', '2026-09-14'), ('2026-09-14', '2026-10-14'), ('2026-10-14', '2026-10-24')]
    assert idk.windows(7, TODAY) == [(date(2026, 10, 17), TODAY)]


def test_url_form():
    assert idk.urlFor('CME', date(2026, 10, 17), TODAY) == \
        'https://ccmc.gsfc.nasa.gov/DONKI-API/get/CME?startDate=2026-10-17&endDate=2026-10-24'


# --- Run ----------------------------------------------------------------------

def test_run_asks_for_the_last_seven_days_of_each_type(db):
    seen = []
    idk.runIngestion(db, fetcher(seen=seen), today=TODAY)
    assert [u.split('/get/')[1] for u in seen] == [f'{t}?startDate=2026-10-17&endDate=2026-10-24' for t in idk.TYPES]


def test_run_stores_every_type_and_a_repeat_changes_nothing(db):
    changes, failed, note = idk.runIngestion(db, fetcher(), today=TODAY)
    assert not failed and changes == 10
    assert (count(db, 'CME'), count(db, 'FLR'), count(db, 'GST'), count(db, 'HSS'), count(db, 'IPS'),
            count(db, 'SEP')) == (2, 2, 2, 2, 2, 0)
    assert note == 'CME 2, HSS 2, GST 2, SEP 0, FLR 2, IPS 2'
    assert idk.runIngestion(db, fetcher(), today=TODAY) == (0, False, note)


def test_a_revised_event_is_a_change(db):
    idk.runIngestion(db, fetcher(), today=TODAY)
    raw = json.loads(fixtureText('FLR'))
    raw[0]['classType'] = 'M2.0'
    raw[0]['versionId'] = 2
    changes, failed, _ = idk.runIngestion(db, fetcher({'FLR': json.dumps(raw)}), today=TODAY)
    assert (changes, failed) == (1, False)
    assert count(db, 'FLR') == 2
    assert json.loads(db.execute('SELECT json FROM events WHERE eventID = ?', (raw[0]['flrID'],)).fetchone()[0])['classType'] == 'M2.0'


def test_events_that_leave_the_window_stay(db):
    idk.runIngestion(db, fetcher(), today=TODAY)
    idk.runIngestion(db, fetcher({'CME': '[]'}), today=TODAY)
    assert count(db, 'CME') == 2


def test_a_surprise_shape_stores_nothing_of_that_type_and_fails_the_run(db):
    raw = json.loads(fixtureText('GST'))
    del raw[1]['startTime']
    changes, failed, note = idk.runIngestion(db, fetcher({'GST': json.dumps(raw)}), today=TODAY)
    assert failed and 'GST: FeedError' in note and 'startTime' in note
    assert count(db, 'GST') == 0           # not even the good first record
    assert count(db, 'CME') == 2 and changes > 0


def test_an_unreachable_type_fails_the_run_and_keeps_what_we_hold(db):
    idk.runIngestion(db, fetcher(), today=TODAY)
    changes, failed, note = idk.runIngestion(db, fetcher(fail=('CME',)), today=TODAY)
    assert failed and changes == 0 and 'CME: Exception: HTTP 503' in note
    assert count(db, 'CME') == 2


def test_backfill_walks_the_stretches_for_every_type(db):
    seen = []
    changes, failed, note = idk.runIngestion(db, fetcher(seen=seen), backfillDays=45, today=TODAY)
    assert not failed
    assert len(seen) == 2 * len(idk.TYPES)
    assert seen[0].endswith('CME?startDate=2026-09-09&endDate=2026-10-09')
    assert seen[1].endswith('CME?startDate=2026-10-09&endDate=2026-10-24')
    assert count(db, 'CME') == 2   # the same fixture answers both stretches; one record per event


def test_main_records_a_failed_run(tmp_path, monkeypatch):
    path = str(tmp_path / 'ingestionDONKI.db')
    monkeypatch.setattr(idk, 'openDb', lambda: idk.connect(path))
    monkeypatch.setattr(idk, 'PacedFetcher', lambda: fetcher({'IPS': 'nonsense'}))
    assert idk.main([]) == 1
    run = sqlite3.connect(path).execute('SELECT job, succeeded, changes, note FROM ingestionRuns').fetchone()
    assert run[:2] == ('donki', 0) and run[2] > 0 and 'IPS: FeedError' in run[3]


def test_main_with_backfill_passes_the_days_on(tmp_path, monkeypatch):
    path = str(tmp_path / 'ingestionDONKI.db')
    seen = []
    monkeypatch.setattr(idk, 'openDb', lambda: idk.connect(path))
    monkeypatch.setattr(idk, 'PacedFetcher', lambda: fetcher(seen=seen))
    assert idk.main(['--backfill', '60']) == 0
    assert len(seen) == 2 * len(idk.TYPES)
