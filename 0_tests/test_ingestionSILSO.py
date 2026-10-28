"""Tests for scripts/ingestionSILSO.py -- against a temporary database and the
WDC-SILSO monthly file recorded on 2026-10-24 (0_tests/fixtures/silsoMonthly.csv);
nothing touches the network."""

import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(TESTS_DIR), 'scripts'))
import ingestionSILSO as silso  # noqa: E402
from spaceWeatherSamples import FeedError  # noqa: E402


def fixture():
    with open(os.path.join(TESTS_DIR, 'fixtures', 'silsoMonthly.csv'), encoding='utf-8') as f:
        return f.read()


@pytest.fixture
def db(tmp_path):
    conn = silso.openDb(str(tmp_path / 'ingestionSILSO.db'))
    yield conn
    conn.close()


def rowFor(rows, series, ts):
    return next(r for r in rows if r[0] == series and r[1] == ts)


def test_monthly_file_gives_mean_std_and_observations_with_a_quality():
    rows = silso.parseMonthly(fixture())
    assert len(rows) == 3 * 3333
    assert rowFor(rows, 'silsoMonthlyMean', '2026-09-01T00:00:00Z') == ('silsoMonthlyMean', '2026-09-01T00:00:00Z', 60.3, 'count', 'provisional')
    assert rowFor(rows, 'silsoMonthlyStd', '2026-09-01T00:00:00Z')[2] == 13.0
    assert rowFor(rows, 'silsoMonthlyObs', '2026-09-01T00:00:00Z')[2] == 1117.0
    assert rowFor(rows, 'silsoMonthlyMean', '2026-06-01T00:00:00Z')[4] == 'definitive'


def test_the_early_record_has_no_std_or_observations():
    rows = silso.parseMonthly(fixture())
    assert rowFor(rows, 'silsoMonthlyMean', '1749-01-01T00:00:00Z')[2] == 96.7
    assert rowFor(rows, 'silsoMonthlyStd', '1749-01-01T00:00:00Z')[2] is None
    assert rowFor(rows, 'silsoMonthlyObs', '1749-01-01T00:00:00Z')[2] is None


@pytest.mark.parametrize('damage', [
    lambda t: '\n'.join(t.splitlines()[:100]),                    # cut off
    lambda t: t.replace('1749;01;1749.042;  96.7', '1749;01;1749.042;  ', 1),
    lambda t: t.replace(';1\n', ';7\n', 1),
    lambda t: t.replace('1749;02;', '1749;13;', 1),
    lambda t: t.replace('1749;02;', '1749;01;', 1),               # not in order
    lambda t: t + '2026;10;2026.8;1;2\n',
    lambda t: '<html>503</html>'])
def test_surprises_reject_the_whole_file(damage):
    with pytest.raises(FeedError):
        silso.parseMonthly(damage(fixture()))


def test_first_run_stores_everything_and_a_repeat_downloads_nothing(db):
    calls = []

    def fetch(url):
        calls.append(url)
        return fixture()

    stamp = 'Tue, 13 Oct 2026 07:32:38 GMT'
    changes, failed, note = silso.runIngestion(db, fetch, head=lambda: stamp)
    assert not failed and changes == 3 * 3333 - 0 and len(calls) == 1
    again = silso.runIngestion(db, fetch, head=lambda: stamp)
    assert again[:2] == (0, False) and len(calls) == 1 and 'unchanged' in again[2]
    assert silso.runIngestion(db, fetch, head=lambda: 'Wed, 11 Nov 2026 07:00:00 GMT')[0] == 0 and len(calls) == 2


def test_a_provisional_month_becomes_definitive_but_never_the_reverse(db):
    silso.runIngestion(db, lambda url: fixture(), head=lambda: 'a')
    text = fixture().replace('2026;09;2026.705;  60.3; 13.0; 1117;0', '2026;09;2026.705;  61.0; 13.1; 1120;1')
    assert silso.runIngestion(db, lambda url: text, head=lambda: 'b')[0] == 3
    assert db.execute("SELECT value, quality FROM samples WHERE series = 'silsoMonthlyMean' AND tsUtc = '2026-09-01T00:00:00Z'").fetchone() == (61.0, 'definitive')
    silso.runIngestion(db, lambda url: fixture(), head=lambda: 'c')       # SILSO's older provisional text again
    assert db.execute("SELECT value, quality FROM samples WHERE series = 'silsoMonthlyMean' AND tsUtc = '2026-09-01T00:00:00Z'").fetchone() == (61.0, 'definitive')


def test_a_bad_file_fails_the_run_and_stores_nothing(db):
    changes, failed, note = silso.runIngestion(db, lambda url: '<html>503</html>', head=lambda: 'x')
    assert failed and changes == 0 and 'FeedError' in note
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 0
    assert db.execute('SELECT COUNT(*) FROM sourceFiles').fetchone()[0] == 0     # so the next run tries again


def test_a_failed_head_request_still_fetches(db):
    def head():
        raise OSError('HEAD refused')
    assert silso.runIngestion(db, lambda url: fixture(), head=head)[1] is False
    assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] > 0
