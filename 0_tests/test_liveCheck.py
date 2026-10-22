"""Tests for 0_tools/liveCheck.py's judgements -- freshness and response
shapes -- on canned data. The tool itself is run against LIVE by hand;
nothing here touches the network."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '0_tools'))
import liveCheck as lc  # noqa: E402

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def row(data, last, next_, failed=False, changes=5):
    return {'data': data, 'lastRefreshUtc': last, 'nextSyncUtc': next_, 'lastRunFailed': failed, 'changes': changes}


def levels(rows):
    return [level for level, _, _ in lc.judgeFreshness(rows, NOW)]


def test_current_source_is_ok():
    assert levels([row('News', '2026-10-22T11:30:00Z', '2026-10-22T12:00:00Z')]) == ['OK']


def test_failed_last_run_fails():
    assert levels([row('Orbital elements', '2026-10-22T07:00:00Z', '2026-10-22T19:00:00Z', failed=True)]) == ['FAIL']


def test_overdue_beyond_grace_fails_within_grace_is_ok():
    assert levels([row('News', '2026-10-22T10:00:00Z', '2026-10-22T10:30:00Z')]) == ['FAIL']   # 1.5 h late
    assert levels([row('News', '2026-10-22T11:00:00Z', '2026-10-22T11:30:00Z')]) == ['OK']     # 0.5 h late


def test_never_run_is_a_warning():
    assert levels([row('Satellite groups', None, None)]) == ['WARN']


def test_shape_helpers():
    assert lc.nonEmptyList(2, ('a',))([{'a': 1}, {'a': 2}]) is None
    assert 'only 1' in lc.nonEmptyList(2)([{'a': 1}])
    assert 'lack' in lc.nonEmptyList(1, ('b',))([{'a': 1}])
    assert 'expected a list' in lc.nonEmptyList(1)({})
    assert lc.dictWith(('rows',), 'rows', 1)({'rows': [1]}) is None
    assert 'missing' in lc.dictWith(('rows',))({})
    assert 'rows has 0' in lc.dictWith(('rows',), 'rows', 1)({'rows': []})


def test_asset_digest_ignores_line_endings():
    assert lc.digest(b'a\r\nb\r\n') == lc.digest(b'a\nb\n')
