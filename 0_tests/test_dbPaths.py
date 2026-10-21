"""Tests for scripts/dbPaths.py -- in particular that code from master
still finds the live server's databases before its migration (plan step
12): old folder ingestionDBs/, old file names."""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import dbPaths  # noqa: E402


@pytest.fixture
def paths(monkeypatch):
    """dbPaths re-read against a chosen project root."""
    def load(root):
        module = importlib.reload(dbPaths)
        monkeypatch.setattr(module, 'DB_DIR', module.dbDir(str(root)))
        monkeypatch.setattr(module, 'LEGACY', os.path.basename(module.DB_DIR) == module.LEGACY_DB_DIR_NAME)
        return module
    yield load
    importlib.reload(dbPaths)


def test_new_folder_uses_new_names(tmp_path, paths):
    (tmp_path / 'databases').mkdir()
    p = paths(tmp_path)
    assert p.dbPath(p.GCAT_DB) == str(tmp_path / 'databases' / 'ingestionGCAT.db')
    assert p.dbPath(p.NEWS_DB) == str(tmp_path / 'databases' / 'ingestionNews.db')


def test_legacy_folder_uses_old_names(tmp_path, paths):
    (tmp_path / 'ingestionDBs').mkdir()
    p = paths(tmp_path)
    assert p.LEGACY
    assert p.dbPath(p.GCAT_DB) == str(tmp_path / 'ingestionDBs' / 'gcat.db')
    assert p.dbPath(p.NEWS_DB) == str(tmp_path / 'ingestionDBs' / 'space_news.db')
    assert p.dbPath(p.GROUND_SEGMENT_DB) == str(tmp_path / 'ingestionDBs' / 'groundSegmentAssets.db')
    assert p.dbPath(p.SKY_DB) == str(tmp_path / 'ingestionDBs' / 'skyCatalogue.db')
    # Names that never changed, and the new source databases, pass through.
    assert p.dbPath(p.ORBITAL_DB) == str(tmp_path / 'ingestionDBs' / 'orbitalObjects.db')
    assert p.dbPath(p.SPACETRACK_DB) == str(tmp_path / 'ingestionDBs' / 'ingestionSpaceTrack.db')


def test_new_folder_wins_when_both_exist(tmp_path, paths):
    (tmp_path / 'databases').mkdir()
    (tmp_path / 'ingestionDBs').mkdir()
    p = paths(tmp_path)
    assert not p.LEGACY
    assert p.dbPath(p.GCAT_DB).endswith(os.path.join('databases', 'ingestionGCAT.db'))
