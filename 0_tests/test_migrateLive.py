"""Tests for scripts/migrateLive.py and scripts/installReferenceDbs.py --
in temporary folders standing in for the server's app folder. The full
migration (ingestion, publish) is rehearsed on a copy of the app with
LIVE's databases; these cover the parts that must never go wrong."""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import dbPaths  # noqa: E402
import installReferenceDbs as ird  # noqa: E402
import migrateLive as ml  # noqa: E402


def makeDb(path, rows=1):
    db = sqlite3.connect(str(path))
    db.execute('CREATE TABLE t (x INTEGER)')
    db.executemany('INSERT INTO t VALUES (?)', [(i,) for i in range(rows)])
    db.commit()
    db.close()


@pytest.fixture
def app(tmp_path, monkeypatch):
    """An app folder on the old layout."""
    old = tmp_path / 'ingestionDBs'
    old.mkdir()
    for name in ('gcat.db', 'space_news.db', 'orbitalObjects.db', 'skyCatalogue.db', 'groundSegmentAssets.db'):
        makeDb(old / name)
    (tmp_path / 'spacetrack.env').write_text('SPACETRACK_USER=x\n')
    monkeypatch.setattr(ml, 'ROOT', str(tmp_path))
    monkeypatch.setattr(ml, 'OLD_DIR', str(old))
    monkeypatch.setattr(ml, 'NEW_DIR', str(tmp_path / 'databases'))
    return tmp_path


def test_preconditions_pass_on_the_old_layout(app):
    assert all(ok for ok, _ in ml.preconditions(str(app)))


def test_already_migrated_refuses(app):
    (app / 'databases').mkdir()
    checks = dict((message.split(':')[0], ok) for ok, message in ml.preconditions(str(app)))
    assert checks['new layout absent'] is False
    with pytest.raises(ml.Failed, match='preconditions'):
        ml.migrate(apply=True, backupRoot=str(app), cron=False, restart=False)
    assert (app / 'ingestionDBs').is_dir()


def test_damaged_database_refuses(app):
    (app / 'ingestionDBs' / 'space_news.db').write_bytes(b'not a database' * 100)
    assert not all(ok for ok, _ in ml.preconditions(str(app)))


def test_dry_run_changes_nothing(app):
    assert ml.migrate(apply=False, backupRoot=str(app), cron=False, restart=False) is None
    assert (app / 'ingestionDBs').is_dir() and not (app / 'databases').exists()
    assert not any(p.name.startswith('dbBackup-') for p in app.iterdir())


def test_backup_and_rename(app):
    ml.backup(str(app / 'backup'))
    assert sorted(os.listdir(app / 'backup')) == sorted(os.listdir(app / 'ingestionDBs'))
    ml.checkpointAndRename()
    assert not (app / 'ingestionDBs').exists()
    assert sorted(os.listdir(app / 'databases')) == ['ingestionGCAT.db', 'ingestionGroundSegment.db',
                                                     'ingestionNews.db', 'ingestionSkyCatalogue.db',
                                                     'orbitalObjects.db']


def test_rollback_restores_the_old_layout(app):
    ml.backup(str(app / 'backup'))
    ml.checkpointAndRename()
    ml.rollback(str(app / 'backup'), apply=True, cron=False, restart=False)
    assert sorted(os.listdir(app / 'ingestionDBs')) == sorted(os.listdir(app / 'backup'))
    assert any(p.name.startswith('databases.failed-') for p in app.iterdir())


def test_rollback_refuses_over_an_existing_old_layout(app):
    ml.backup(str(app / 'backup'))
    with pytest.raises(ml.Failed, match='already exists'):
        ml.rollback(str(app / 'backup'), apply=True, cron=False, restart=False)


# --- installReferenceDbs -----------------------------------------------------------

@pytest.fixture
def migrated(tmp_path, monkeypatch):
    dbDir = tmp_path / 'databases'
    dbDir.mkdir()
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(dbDir))
    monkeypatch.setattr(dbPaths, 'LEGACY', False)
    monkeypatch.setattr(ird, 'DB_DIR', str(dbDir))
    upload = tmp_path / 'upload'
    upload.mkdir()
    return dbDir, upload


def test_changed_reference_db_is_installed_and_published(migrated):
    dbDir, upload = migrated
    makeDb(dbDir / 'ingestionGroundSegment.db', 1)
    makeDb(upload / 'ingestionGroundSegment.db', 2)
    published = []
    results = dict(ird.install(str(upload), lambda kind: published.append(kind) or {'t': 2}))
    assert results['ingestionGroundSegment.db'].startswith('installed')
    assert results['ingestionSkyCatalogue.db'] == 'not uploaded'
    assert published == ['groundSegment']
    db = sqlite3.connect(str(dbDir / 'ingestionGroundSegment.db'))
    assert db.execute('SELECT COUNT(*) FROM t').fetchone()[0] == 2
    db.close()


def test_identical_reference_db_is_left_alone(migrated):
    dbDir, upload = migrated
    makeDb(dbDir / 'ingestionGroundSegment.db')
    (upload / 'ingestionGroundSegment.db').write_bytes((dbDir / 'ingestionGroundSegment.db').read_bytes())
    results = dict(ird.install(str(upload), lambda kind: pytest.fail('published')))
    assert results['ingestionGroundSegment.db'] == 'unchanged'


def test_damaged_upload_is_rejected(migrated):
    dbDir, upload = migrated
    makeDb(dbDir / 'ingestionGroundSegment.db')
    (upload / 'ingestionGroundSegment.db').write_bytes(b'garbage' * 100)
    results = dict(ird.install(str(upload), lambda kind: pytest.fail('published')))
    assert results['ingestionGroundSegment.db'].startswith('REJECTED')


def test_unmigrated_server_discards_uploads(tmp_path, monkeypatch):
    legacy = tmp_path / 'ingestionDBs'
    legacy.mkdir()
    monkeypatch.setattr(dbPaths, 'LEGACY', True)
    monkeypatch.setattr(ird, 'DB_DIR', str(legacy))
    assert ird.install(str(tmp_path), lambda kind: pytest.fail('published')) == [
        ('*', 'server not migrated yet -- uploads discarded')]
