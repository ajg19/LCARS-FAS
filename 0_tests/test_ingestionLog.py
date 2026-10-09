"""Tests for scripts/ingestionLog.py -- run recording for the landing
page's data-freshness table. In-memory databases only.

Run with:  pytest 0_tests/ -v
"""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import ingestionLog  # noqa: E402
from ingestionLog import recordRun, trackRun  # noqa: E402


def runs(db, job):
    return db.execute(
        'SELECT succeeded, changes, note FROM ingestionRuns WHERE job = ? ORDER BY id', (job,)).fetchall()


def test_successful_run_is_recorded_with_its_changes():
    db = sqlite3.connect(':memory:')
    with trackRun(db, 'news') as run:
        run.changes = 12
    assert runs(db, 'news') == [(1, 12, None)]


def test_exception_is_recorded_as_failure_and_re_raised():
    db = sqlite3.connect(':memory:')
    with pytest.raises(ValueError):
        with trackRun(db, 'satcat'):
            raise ValueError('feed down')
    [(succeeded, changes, note)] = runs(db, 'satcat')
    assert succeeded == 0
    assert 'feed down' in note


def test_failed_flag_records_failure_without_raising():
    db = sqlite3.connect(':memory:')
    with trackRun(db, 'satnogsRf') as run:
        run.failed = True
        run.note = 'fetch failed'
    assert runs(db, 'satnogsRf') == [(0, None, 'fetch failed')]


def test_old_runs_are_pruned_per_job(monkeypatch):
    monkeypatch.setattr(ingestionLog, 'KEEP_RUNS_PER_JOB', 3)
    db = sqlite3.connect(':memory:')
    for i in range(5):
        recordRun(db, 'news', '2026-10-09T00:00:00Z', True, i)
    recordRun(db, 'eirp', '2026-10-09T00:00:00Z', True, 99)
    assert [changes for _, changes, _ in runs(db, 'news')] == [2, 3, 4]
    assert len(runs(db, 'eirp')) == 1
