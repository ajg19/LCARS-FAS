"""Tests for scripts/publishSite.py -- in a temporary database folder
(dbPaths.DB_DIR redirected), never the real databases/. The full orbital
publish (stats, brightness, EIRP over the real GCAT) is exercised by
running it on DEV; these cover the publish mechanics and the orbital
steps with rules of their own: object selection and transmitter
linking."""

import os
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import dbPaths  # noqa: E402
import ingestionSatNOGS  # noqa: E402
import ingestionSpaceTrack  # noqa: E402
import publishSite as ps  # noqa: E402

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


@pytest.fixture
def dbDir(tmp_path, monkeypatch):
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(dbPaths, 'LEGACY', False)
    return tmp_path


def makeGroundSegment(rows):
    db = sqlite3.connect(dbPaths.dbPath(dbPaths.GROUND_SEGMENT_DB))
    db.execute('DROP TABLE IF EXISTS ground_segment_assets')
    db.execute('CREATE TABLE ground_segment_assets (id INTEGER PRIMARY KEY, name TEXT)')
    db.executemany('INSERT INTO ground_segment_assets (name) VALUES (?)', [(f'site {i}',) for i in range(rows)])
    db.commit()
    db.close()


def siteRows(name='siteGroundSegment.db'):
    db = sqlite3.connect(dbPaths.dbPath(name))
    n = db.execute('SELECT COUNT(*) FROM ground_segment_assets').fetchone()[0]
    db.close()
    return n


# --- Publish mechanics --------------------------------------------------------

def test_publish_builds_swaps_and_keeps_prev(dbDir):
    makeGroundSegment(100)
    assert ps.publish('groundSegment') == {'ground_segment_assets': 100}
    makeGroundSegment(95)
    ps.publish('groundSegment')
    assert siteRows() == 95
    assert siteRows('siteGroundSegment.db.prev') == 100
    assert not os.path.exists(dbPaths.dbPath('siteGroundSegment.db.tmp'))


def test_large_drop_is_refused_and_live_file_untouched(dbDir):
    makeGroundSegment(100)
    ps.publish('groundSegment')
    makeGroundSegment(50)
    with pytest.raises(ps.PublishRefused, match='would drop from 100 to 50'):
        ps.publish('groundSegment')
    assert siteRows() == 100
    assert not os.path.exists(dbPaths.dbPath('siteGroundSegment.db.tmp'))
    ps.publish('groundSegment', force=True)
    assert siteRows() == 50


def test_empty_table_is_refused(dbDir):
    makeGroundSegment(0)
    with pytest.raises(ps.PublishRefused, match='empty table'):
        ps.publish('groundSegment')
    assert not os.path.exists(dbPaths.dbPath('siteGroundSegment.db'))


def test_copy_keeps_indexes(dbDir):
    makeGroundSegment(3)
    db = sqlite3.connect(dbPaths.dbPath(dbPaths.GROUND_SEGMENT_DB))
    db.execute('CREATE INDEX byName ON ground_segment_assets (name)')
    db.commit()
    db.close()
    ps.publish('groundSegment')
    site = sqlite3.connect(dbPaths.dbPath('siteGroundSegment.db'))
    assert site.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall() == [('byName',)]
    site.close()


# --- Orbital: object selection -----------------------------------------------------

def gp(norad, epoch, **extra):
    return {'NORAD_CAT_ID': str(norad), 'OBJECT_NAME': f'OBJ {norad}', 'OBJECT_ID': f'2020-{norad:03d}A',
            'OBJECT_TYPE': 'PAYLOAD', 'EPOCH': epoch, 'MEAN_MOTION': '15.0', **extra}


def makeSpaceTrack(full, recent=(), decays=()):
    db = ingestionSpaceTrack.openDb(dbPaths.dbPath(dbPaths.SPACETRACK_DB))
    ingestionSpaceTrack.storeEntries(db, full, '2026-10-20T00:00:00Z', seenFull='2026-10-20T00:00:00Z')
    ingestionSpaceTrack.storeEntries(db, recent, '2026-10-21T00:00:00Z')
    ingestionSpaceTrack.storeEntries(db, decays, '2026-10-20T00:00:00Z')
    db.close()


def staged(dbDir):
    path = str(dbDir / 'stage.db')
    ps.buildObjects(path, NOW)
    db = sqlite3.connect(path)
    return db, path


def test_selection_and_mapping(dbDir):
    makeSpaceTrack(
        full=[gp(1, '2026-10-19T00:00:00'), gp(2, '2026-09-01T00:00:00'),
              gp(3, '2026-10-19T00:00:00', OBJECT_TYPE='ROCKET BODY', RCS_SIZE='LARGE')],
        recent=[gp(4, '2026-10-20T00:00:00')],
        decays=[gp(5, '2026-10-10T00:00:00', DECAY_DATE='2026-10-12'),
                gp(6, '2026-07-01T00:00:00', DECAY_DATE='2026-07-03')])
    db, _ = staged(dbDir)
    rows = {r[0]: r[1:] for r in db.execute('SELECT noradID, epoch, objectType, rcsSize, rcsCategory, '
                                            'decayDate, source FROM orbital_objects')}
    # 2: element set older than MAX_ELEMENT_AGE_DAYS; 6: decayed too long ago.
    assert set(rows) == {1, 3, 4, 5}
    assert rows[1][0] == '2026-10-19T00:00:00Z'
    assert rows[3][1:4] == ('R/B', None, 'LARGE')
    assert rows[5][4] == '2026-10-12'
    assert rows[1][5] == 'space-track'
    db.close()


def test_rcs_comes_from_kept_celestrak_figures(dbDir):
    import ingestionCelesTrak
    makeSpaceTrack(full=[gp(1, '2026-10-19T00:00:00', RCS_SIZE='LARGE'), gp(2, '2026-10-19T00:00:00')])
    ct = ingestionCelesTrak.openDb(dbPaths.dbPath(dbPaths.CELESTRAK_DB))
    ingestionCelesTrak.storeRcs(ct, [(1, 12.5), (99, 1.0)], 'T1')
    ct.close()
    db, _ = staged(dbDir)
    assert dict(db.execute('SELECT noradID, rcsSize FROM orbital_objects')) == {1: 12.5, 2: None}
    assert db.execute('SELECT rcsCategory FROM orbital_objects WHERE noradID = 1').fetchone()[0] == 'LARGE'
    db.close()


def test_object_that_left_the_catalogue_is_not_published(dbDir):
    db = ingestionSpaceTrack.openDb(dbPaths.dbPath(dbPaths.SPACETRACK_DB))
    ingestionSpaceTrack.storeEntries(db, [gp(1, '2026-10-19T00:00:00'), gp(2, '2026-10-19T00:00:00')],
                                     '2026-10-19T00:00:00Z', seenFull='2026-10-19T00:00:00Z')
    ingestionSpaceTrack.storeEntries(db, [gp(1, '2026-10-19T00:00:00')], '2026-10-20T00:00:00Z',
                                     seenFull='2026-10-20T00:00:00Z')
    db.close()
    site, _ = staged(dbDir)
    assert [r[0] for r in site.execute('SELECT noradID FROM orbital_objects')] == [1]
    site.close()


def test_no_full_pass_refuses(dbDir):
    ingestionSpaceTrack.openDb(dbPaths.dbPath(dbPaths.SPACETRACK_DB)).close()
    with pytest.raises(ps.PublishRefused, match='no full pass'):
        ps.buildObjects(str(dbDir / 'stage.db'), NOW)


# --- Orbital: transmitter linking --------------------------------------------------

def tx(uuid, norad, follow=None, low=437e6):
    return {'uuid': uuid, 'norad_cat_id': norad, 'norad_follow_id': follow, 'downlink_low': low,
            'downlink_high': low, 'mode': 'GMSK', 'baud': 9600, 'status': 'active', 'alive': True,
            'frequency_violation': False, 'unconfirmed': False, 'updated': '2026-10-01T00:00:00Z'}


def test_transmitters_link_by_follow_then_designator_then_own_number(dbDir):
    makeSpaceTrack(full=[gp(101, '2026-10-19T00:00:00'), gp(102, '2026-10-19T00:00:00', OBJECT_ID='2026-229K'),
                         gp(103, '2026-10-19T00:00:00')])
    sn = ingestionSatNOGS.openDb(dbPaths.dbPath(dbPaths.SATNOGS_DB))
    ingestionSatNOGS.storeTles(sn, [{
        'norad_cat_id': 98193, 'tle0': '0 OBJECT K', 'tle_source': 'Space-Track.org',
        'tle1': '1 98193U 26229K   26292.94310762  .00002430  00000-0  20933-3 0  9993',
        'tle2': '2 98193  97.6979  28.9262 0012856  39.3768 320.8386 14.98205746  1935'}], '2026-10-21T00:00:00Z')
    ingestionSatNOGS.storeTransmitters(sn, [
        tx('a', 99001, follow=101, low=145.8e6),   # follow id
        tx('b', 98193, low=437.1e6),               # placeholder -> designator 2026-229K -> 102
        tx('c', 103, low=2.2e9),                   # own number
        tx('d', 99999),                            # nothing links it
    ])
    sn.close()
    db, path = staged(dbDir)
    db.close()
    linked, how = ps.linkTransmitters(path)
    assert (linked, how) == (3, {'follow': 1, 'designator': 1, 'own': 1})
    db = sqlite3.connect(path)
    rows = dict(db.execute("SELECT noradID, dlFreqHz FROM orbital_objects WHERE rfSource = 'satnogs'"))
    assert rows == {101: 145.8e6, 102: 437.1e6, 103: 2.2e9}
    db.close()
