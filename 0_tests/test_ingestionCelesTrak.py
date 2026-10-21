"""Tests for scripts/ingestionCelesTrak.py -- against a temporary
database and canned CelesTrak responses; nothing touches the network or
the real databases/ingestionCelesTrak.db."""

import calendar
import os
import socket
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import ingestionCelesTrak as ict  # noqa: E402

# Shape of a gp.php FORMAT=csv response (header plus rows, trimmed).
CSV = ('OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION,ECCENTRICITY,INCLINATION,NORAD_CAT_ID\r\n'
       'ISS (ZARYA),1998-067A,2026-10-21T11:59:19.095648,15.48973463,.0006826,51.6330,25544\r\n'
       'CSS (TIANHE),2021-035A,2026-10-21T10:00:00.000000,15.6,.0005,41.47,48274\r\n')


@pytest.fixture
def db(tmp_path):
    conn = ict.openDb(str(tmp_path / 'ingestionCelesTrak.db'))
    yield conn
    conn.close()


def members(db, group):
    return {r[0] for r in db.execute('SELECT noradID FROM groupMembers WHERE groupName = ?', (group,))}


def fetchFrom(responses):
    """A fetch() answering from a dict: group -> members list, ('skipped', note) or an exception."""
    def fetch(group):
        result = responses[group]
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, tuple):
            return result
        return 'ok', result
    return fetch


def test_parse_members_from_csv():
    assert ict.parseMembers(CSV) == [(25544, 'ISS (ZARYA)'), (48274, 'CSS (TIANHE)')]


def test_parse_skips_bad_rows():
    assert ict.parseMembers(CSV + 'BROKEN,x,y,1,2,3,notanumber\r\n') == [(25544, 'ISS (ZARYA)'), (48274, 'CSS (TIANHE)')]


def test_store_replaces_membership_and_counts_changes(db):
    ict.recordAttempt(db, 'stations', 'T1')
    assert ict.storeGroup(db, 'stations', [(1, 'A'), (2, 'B')], 'T1') == 2
    assert ict.storeGroup(db, 'stations', [(2, 'B'), (3, 'C')], 'T2') == 2  # 1 removed, 3 added
    assert members(db, 'stations') == {2, 3}
    assert ict.storeGroup(db, 'stations', [(2, 'B'), (3, 'C')], 'T3') == 0
    assert db.execute("SELECT lastSuccess, members FROM groupFetches WHERE groupName = 'stations'").fetchone() == ('T3', 2)


def test_pass_records_success_skip_and_error(db):
    fetch = fetchFrom({
        'stations': [(25544, 'ISS')],
        'starlink': ('skipped', 'GP data has not updated'),
        'active': Exception('HTTP 500'),
    })
    changes, succeeded, failed, note = ict.runPass(db, ['stations', 'starlink', 'active'], fetch, delay=0)
    assert (changes, succeeded, failed) == (1, 1, 1)
    assert 'active: HTTP 500' in note
    rows = dict(db.execute('SELECT groupName, lastSuccess IS NOT NULL FROM groupFetches'))
    assert rows == {'stations': 1, 'starlink': 0, 'active': 0}


def test_error_keeps_previous_membership(db):
    ict.runPass(db, ['stations'], fetchFrom({'stations': [(1, 'A')]}), delay=0)
    ict.runPass(db, ['stations'], fetchFrom({'stations': Exception('HTTP 500')}), delay=0)
    assert members(db, 'stations') == {1}


def test_connection_failure_stops_the_pass(db):
    fetch = fetchFrom({'stations': socket.timeout('timed out'), 'starlink': [(1, 'A')]})
    _, succeeded, failed, note = ict.runPass(db, ['stations', 'starlink'], fetch, delay=0)
    assert (succeeded, failed) == (0, 1)
    assert 'remaining groups skipped' in note
    assert db.execute("SELECT COUNT(*) FROM groupFetches WHERE groupName = 'starlink'").fetchone()[0] == 0


def test_pass_due_without_history(db):
    assert ict.passDue(db, 168 * 3600) == (True, '')


def test_pass_not_due_inside_interval_then_due(db):
    ict.recordAttempt(db, 'stations', '2026-10-21T00:00:00Z')
    t0 = calendar.timegm(time.strptime('2026-10-21T00:00:00Z', '%Y-%m-%dT%H:%M:%SZ'))
    due, reason = ict.passDue(db, 168 * 3600, now=t0 + 3 * 86400)
    assert not due and '2026-10-21T00:00:00Z' in reason
    assert ict.passDue(db, 168 * 3600, now=t0 + 7 * 86400)[0]


def test_fetch_group_treats_not_updated_message_as_skip(monkeypatch):
    monkeypatch.setattr(ict, 'httpGet', lambda url: (403, 'GP data has not updated since your last request\n'))
    assert ict.fetchGroup('active') == ('skipped', 'GP data has not updated since your last request')


def test_fetch_group_rejects_empty_response(monkeypatch):
    monkeypatch.setattr(ict, 'httpGet', lambda url: (200, 'OBJECT_NAME,NORAD_CAT_ID\r\n'))
    with pytest.raises(Exception, match='no members'):
        ict.fetchGroup('active')


def test_disabled_makes_no_request(tmp_path, monkeypatch):
    realOpenDb = ict.openDb
    monkeypatch.setattr(ict, 'openDb', lambda: realOpenDb(str(tmp_path / 'ct.db')))
    monkeypatch.setattr(ict, 'settings', lambda: (False, 168 * 3600))
    monkeypatch.setattr(ict, 'httpGet', lambda url: pytest.fail('CelesTrak was contacted'))
    assert ict.main([]) == 0
