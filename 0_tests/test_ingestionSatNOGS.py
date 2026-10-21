"""Tests for scripts/ingestionSatNOGS.py -- against a temporary database
and SatNOGS records recorded on 2026-10-21 (0_tests/fixtures/); nothing
touches the network or the real databases/ingestionSatNOGS.db."""

import json
import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(TESTS_DIR), 'scripts'))
import ingestionSatNOGS as isn  # noqa: E402


def fixture(name):
    with open(os.path.join(TESTS_DIR, 'fixtures', name), encoding='utf-8') as f:
        return json.load(f)


TLES = fixture('satnogsTle.json')            # ISS, NEMO-HD, OBJECT G
TRANSMITTERS = fixture('satnogsTransmitters.json')  # four records for NORAD 965


@pytest.fixture
def db(tmp_path):
    conn = isn.openDb(str(tmp_path / 'ingestionSatNOGS.db'))
    yield conn
    conn.close()


def tle(db, norad, column):
    return db.execute(f'SELECT {column} FROM tle WHERE noradID = ?', (norad,)).fetchone()[0]


def withEpochDay(record, day):
    """The record with line 1's epoch day-of-year replaced (checksum not
    recomputed -- nothing here checks it)."""
    line1 = record['tle1']
    return {**record, 'tle1': line1[:20] + f'{day:012.8f}' + line1[32:]}


# --- TLE decoding -------------------------------------------------------------

def test_iss_decodes_to_space_tracks_own_elements():
    # Space-Track's OMM for the same ISS element set, fetched the same day.
    row = isn.tleRow(TLES[0])
    assert row['noradID'] == 25544
    assert row['objectName'] == 'ISS (ZARYA)'
    assert row['tleSource'] == 'Space-Track.org'
    assert row['epoch'] == '2026-10-21T11:59:19.095648'
    assert row['meanMotion'] == pytest.approx(15.48973463)
    assert row['eccentricity'] == pytest.approx(0.0006826)
    assert row['inclination'] == pytest.approx(51.6330)
    assert row['raOfAscNode'] == pytest.approx(35.0282)
    assert row['argOfPericenter'] == pytest.approx(292.5374)
    assert row['meanAnomaly'] == pytest.approx(67.4891)
    assert row['bstar'] == pytest.approx(0.00017299)
    assert row['meanMotionDot'] == pytest.approx(0.00009087)
    assert row['meanMotionDdot'] == 0.0


def test_assumed_decimal_notation():
    assert isn.assumedDecimal(' 17299-3') == pytest.approx(0.17299e-3)
    assert isn.assumedDecimal('-11606-4') == pytest.approx(-0.11606e-4)
    assert isn.assumedDecimal(' 00000-0') == 0.0


def test_twentieth_century_epoch():
    line1 = '1 00005U 58002B   75042.50000000  .00000023  00000-0  28098-4 0  9997'
    assert isn.tleEpoch(line1).startswith('1975-02-11T12:00:00')


def test_undecodable_or_unkeyed_records_are_skipped():
    assert isn.tleRow({**TLES[0], 'tle2': 'garbage'}) is None
    assert isn.tleRow({**TLES[0], 'norad_cat_id': None}) is None


# --- Storing TLEs -------------------------------------------------------------

def test_store_tles_and_repeat_is_not_a_change(db):
    assert isn.storeTles(db, TLES, '2026-10-21T10:00:00Z') == (3, 3, 0)
    assert isn.storeTles(db, TLES, '2026-10-21T22:00:00Z') == (0, 3, 0)
    assert tle(db, 25544, 'lastSeen') == '2026-10-21T22:00:00Z'
    assert tle(db, 25544, 'fetchedAt') == '2026-10-21T10:00:00Z'


def test_older_epoch_never_replaces_newer(db):
    isn.storeTles(db, [TLES[0]], '2026-10-21T10:00:00Z')
    older = withEpochDay(TLES[0], 290.0)
    assert isn.storeTles(db, [older], '2026-10-21T22:00:00Z')[0] == 0
    assert tle(db, 25544, 'epoch') == '2026-10-21T11:59:19.095648'
    newer = withEpochDay(TLES[0], 295.0)
    assert isn.storeTles(db, [newer], '2026-10-22T10:00:00Z')[0] == 1
    assert tle(db, 25544, 'epoch').startswith('2026-10-22')


def test_object_leaving_the_feed_counts_as_a_change(db):
    isn.storeTles(db, TLES, '2026-10-21T10:00:00Z')
    changes, stored, _ = isn.storeTles(db, TLES[:2], '2026-10-21T22:00:00Z')
    assert (changes, stored) == (1, 2)
    assert tle(db, TLES[2]['norad_cat_id'], 'lastSeen') == '2026-10-21T10:00:00Z'


# --- Transmitters ---------------------------------------------------------------

def test_transmitter_row_types():
    row = isn.txRow(TRANSMITTERS[0])
    assert row['noradID'] == 965
    assert row['alive'] == 1 and row['invert'] == 0
    assert row['downlinkLow'] == 136658500.0
    assert row['baud'] is None
    assert json.loads(row['ituNotification']) == {'urls': []}


def test_transmitters_replaced_and_changes_counted(db):
    assert isn.storeTransmitters(db, TRANSMITTERS) == (4, 4)
    assert isn.storeTransmitters(db, TRANSMITTERS) == (0, 4)
    edited = [{**TRANSMITTERS[0], 'updated': '2026-10-21T00:00:00Z'}] + TRANSMITTERS[1:3]
    assert isn.storeTransmitters(db, edited) == (2, 3)  # one updated, one removed
    assert db.execute('SELECT COUNT(*) FROM transmitters').fetchone()[0] == 3


# --- Run ----------------------------------------------------------------------

def test_failed_feed_leaves_its_table_and_fails_the_run(db):
    isn.storeTransmitters(db, TRANSMITTERS)

    def fetch(url):
        if url == isn.TLE_URL:
            return TLES
        raise Exception('HTTP 503')

    changes, failed, note = isn.runIngestion(db, fetch)
    assert failed and 'transmitters: Exception: HTTP 503' in note
    assert changes == 3
    assert db.execute('SELECT COUNT(*) FROM transmitters').fetchone()[0] == 4


def test_empty_response_is_an_error(monkeypatch):
    monkeypatch.setattr(isn, 'httpGet', lambda url, headers=None: (200, '[]'))
    with pytest.raises(Exception, match='empty response'):
        isn.fetchList(isn.TLE_URL)
