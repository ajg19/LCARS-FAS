"""Tests for 0_tools/liveCheck.py's judgements -- freshness, privacy and
response shapes -- on canned data. The tool itself is run against LIVE
by hand; nothing here touches the network."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '0_tools'))
import liveCheck as lc  # noqa: E402

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
BOT_PAGE = b'<html><body>One moment, please... Please wait while your request is being verified...</body></html>'


def row(data, last, next_, failed=False, changes=5):
    return {'data': data, 'lastRefreshUtc': last, 'nextSyncUtc': next_, 'lastRunFailed': failed, 'changes': changes}


def judged(rows):
    return lc.judgeFreshness(rows, NOW)


# --- Freshness ---------------------------------------------------------------------

def test_current_source_is_ok_and_says_when_next():
    [(level, text)] = judged([row('News', '2026-10-22T11:30:00Z', '2026-10-22T12:00:00Z')])
    assert level == 'OK' and text == 'News up to date: refreshed 30 min ago, next due 12:00Z'


def test_failed_last_run_fails_and_says_what_the_site_shows():
    [(level, text)] = judged([row('Orbital elements', '2026-10-22T07:00:00Z', '2026-10-22T19:00:00Z', failed=True)])
    assert level == 'FAIL' and 'last run failed' in text and '2026-10-22T07:00Z' in text


def test_overdue_beyond_grace_fails_within_grace_is_ok():
    [(level, text)] = judged([row('News', '2026-10-22T10:00:00Z', '2026-10-22T10:30:00Z')])   # 1.5 h late
    assert level == 'FAIL' and '1.5 h overdue' in text and 'cron job' in text
    assert judged([row('News', '2026-10-22T11:00:00Z', '2026-10-22T11:30:00Z')])[0][0] == 'OK'  # 0.5 h late


def test_never_run_is_a_warning():
    [(level, text)] = judged([row('Satellite groups', None, None)])
    assert level == 'WARN' and 'never refreshed' in text


# --- Privacy -----------------------------------------------------------------------

def test_refused_private_file_is_ok():
    assert lc.judgeExposure('server.py', 'server code', 403, b'403 Forbidden')[0] == 'OK'
    assert lc.judgeExposure('x.db', 'db', 404, b'')[0] == 'OK'


def test_downloadable_private_file_fails():
    level, text = lc.judgeExposure('databases/siteOrbital.db.prev', 'previous site database', 206, b'SQLite format 3\x00')
    assert level == 'FAIL' and 'EXPOSED' in text and '.htaccess' in text


def test_bot_check_page_is_not_mistaken_for_a_file():
    assert lc.judgeExposure('setupCron.sh', 'cron installer', 200, BOT_PAGE)[0] == 'WARN'
    assert lc.isBotCheck(BOT_PAGE) and not lc.isBotCheck(b'{"rows": []}')


def test_truncated_bot_page_without_marker_is_not_mistaken_for_a_file():
    # Only the first 1 KB is read; the bot page's marker text sits further in.
    head = b'<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="utf8">'
    assert lc.judgeExposure('databases/siteOrbital.db.prev', 'previous site database', 200, head)[0] == 'WARN'


def test_every_private_path_is_described():
    assert all(path and what for path, what in lc.PRIVATE)


# --- Shapes and helpers ---------------------------------------------------------------

def test_shape_helpers_return_problem_and_count():
    assert lc.nonEmptyList(2, ('a',))([{'a': 1}, {'a': 2}]) == (None, 2)
    assert lc.nonEmptyList(2)([{'a': 1}]) == ('only 1 items, expected at least 2', 1)
    assert lc.nonEmptyList(1, ('b',))([{'a': 1}])[0] == 'items lack b'
    assert 'expected a list' in lc.nonEmptyList(1)({})[0]
    assert lc.dictWith(('rows',), 'rows', 1)({'rows': [1]}) == (None, 1)
    assert 'missing rows' in lc.dictWith(('rows',))({})[0]
    assert 'only 0 items' in lc.dictWith(('rows',), 'rows', 1)({'rows': []})[0]


def test_sizes_and_durations_read_naturally():
    assert (lc.size(512), lc.size(34_132), lc.size(14_015_154)) == ('512 B', '34 KB', '14.0 MB')
    assert lc.hours(NOW - datetime(2026, 10, 22, 11, 20, tzinfo=timezone.utc)) == '40 min'
    assert lc.hours(NOW - datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)) == '4.0 days'


def test_asset_digest_ignores_line_endings():
    assert lc.digest(b'a\r\nb\r\n') == lc.digest(b'a\nb\n')
