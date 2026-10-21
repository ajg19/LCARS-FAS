"""Tests for scripts/ingestionSpaceTrack.py -- against a temporary
database and recorded Space-Track GP records; nothing touches the
network or the real databases/ingestionSpaceTrack.db."""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import ingestionSpaceTrack as ist  # noqa: E402
from ingestionLog import recordRun  # noqa: E402

# ISS as Space-Track returned it on 2026-10-21 (TLE lines trimmed).
ISS = {
    'CCSDS_OMM_VERS': '3.0', 'COMMENT': 'GENERATED VIA SPACE-TRACK.ORG API',
    'CREATION_DATE': '2026-10-21T16:26:48', 'ORIGINATOR': '18 SPCS', 'OBJECT_NAME': 'ISS (ZARYA)',
    'OBJECT_ID': '1998-067A', 'CENTER_NAME': 'EARTH', 'REF_FRAME': 'TEME', 'TIME_SYSTEM': 'UTC',
    'MEAN_ELEMENT_THEORY': 'SGP4', 'EPOCH': '2026-10-21T11:59:19.095648', 'MEAN_MOTION': '15.48973463',
    'ECCENTRICITY': '0.00068260', 'INCLINATION': '51.6330', 'RA_OF_ASC_NODE': '35.0282',
    'ARG_OF_PERICENTER': '292.5374', 'MEAN_ANOMALY': '67.4891', 'EPHEMERIS_TYPE': '0',
    'CLASSIFICATION_TYPE': 'U', 'NORAD_CAT_ID': '25544', 'ELEMENT_SET_NO': '999', 'REV_AT_EPOCH': '59133',
    'BSTAR': '0.00017299000000', 'MEAN_MOTION_DOT': '0.00009087', 'MEAN_MOTION_DDOT': '0.0000000000000',
    'SEMIMAJOR_AXIS': '6797.865', 'PERIOD': '92.965', 'APOAPSIS': '424.370', 'PERIAPSIS': '415.090',
    'OBJECT_TYPE': 'PAYLOAD', 'RCS_SIZE': 'LARGE', 'COUNTRY_CODE': 'CIS', 'LAUNCH_DATE': '1998-11-20',
    'SITE': 'TTMTR', 'DECAY_DATE': None, 'FILE': '5398348', 'GP_ID': '353980846',
    'TLE_LINE0': '0 ISS (ZARYA)', 'TLE_LINE1': '1 25544U ...', 'TLE_LINE2': '2 25544 ...',
}


def gp(norad, epoch, **extra):
    return {**ISS, 'NORAD_CAT_ID': str(norad), 'OBJECT_NAME': f'OBJ {norad}', 'EPOCH': epoch, **extra}


@pytest.fixture
def db(tmp_path):
    conn = ist.openDb(str(tmp_path / 'ingestionSpaceTrack.db'))
    yield conn
    conn.close()


def stored(db, norad, column):
    return db.execute(f'SELECT {column} FROM gp WHERE noradID = ?', (norad,)).fetchone()[0]


class FakeSpaceTrack:
    """Stands in for common.SpaceTrack: answers queries from a dict."""

    def __init__(self, responses):
        self.responses = responses
        self.queries = []
        self.loggedIn = False
        self.configured = True

    def __enter__(self):
        self.loggedIn = True
        return self

    def __exit__(self, *exc):
        self.loggedIn = False
        return False

    def get(self, query):
        assert self.loggedIn
        self.queries.append(query)
        status, data = self.responses[query]
        return status, json.dumps(data)


# --- Field mapping --------------------------------------------------------

def test_row_maps_every_field_with_types():
    row = ist.rowFromGp(ISS)
    assert row['noradID'] == 25544
    assert row['objectName'] == 'ISS (ZARYA)'
    assert row['meanMotion'] == pytest.approx(15.48973463)
    assert row['bstar'] == pytest.approx(0.00017299)
    assert row['revAtEpoch'] == 59133
    assert row['rcsSize'] == 'LARGE'
    assert row['decayDate'] is None
    assert row['epoch'] == '2026-10-21T11:59:19.095648'
    assert set(row) == set(ist.COLUMNS)


def test_row_without_norad_id_or_epoch_is_rejected():
    assert ist.rowFromGp({**ISS, 'NORAD_CAT_ID': None}) is None
    assert ist.rowFromGp({**ISS, 'EPOCH': ''}) is None


def test_unparseable_number_becomes_null():
    assert ist.rowFromGp({**ISS, 'MEAN_MOTION': 'n/a'})['meanMotion'] is None


# --- Storing --------------------------------------------------------------

def test_epoch_never_moves_backwards(db):
    ist.storeEntries(db, [gp(1, '2026-10-20T00:00:00')], 'T1')
    assert ist.storeEntries(db, [gp(1, '2026-10-19T00:00:00')], 'T2') == 0
    assert stored(db, 1, 'epoch') == '2026-10-20T00:00:00'
    assert stored(db, 1, 'fetchedAt') == 'T1'
    assert ist.storeEntries(db, [gp(1, '2026-10-21T00:00:00')], 'T3') == 1
    assert stored(db, 1, 'epoch') == '2026-10-21T00:00:00'


def test_same_record_again_is_not_a_change(db):
    ist.storeEntries(db, [gp(1, '2026-10-20T00:00:00')], 'T1')
    assert ist.storeEntries(db, [gp(1, '2026-10-20T00:00:00')], 'T2') == 0
    assert stored(db, 1, 'fetchedAt') == 'T1'


def test_same_epoch_with_new_decay_date_is_a_change(db):
    ist.storeEntries(db, [gp(1, '2026-10-20T00:00:00')], 'T1')
    assert ist.storeEntries(db, [gp(1, '2026-10-20T00:00:00', DECAY_DATE='2026-10-21')], 'T2') == 1
    assert stored(db, 1, 'decayDate') == '2026-10-21'


def test_full_pass_marks_seen_even_when_stored_element_set_is_newer(db):
    ist.storeEntries(db, [gp(1, '2026-10-21T00:00:00')], 'T1')
    ist.storeEntries(db, [gp(1, '2026-10-20T00:00:00')], 'T2', seenFull='T2')
    assert stored(db, 1, 'epoch') == '2026-10-21T00:00:00'
    assert stored(db, 1, 'lastSeenFull') == 'T2'


def test_recent_pass_keeps_last_seen_full(db):
    ist.storeEntries(db, [gp(1, '2026-10-20T00:00:00')], 'T1', seenFull='T1')
    ist.storeEntries(db, [gp(1, '2026-10-21T00:00:00')], 'T2')
    assert stored(db, 1, 'lastSeenFull') == 'T1'


# --- Passes ---------------------------------------------------------------

def test_full_pass_stores_catalogue_and_decays(db):
    fake = FakeSpaceTrack({
        ist.FULL_CATALOGUE_QUERY: (200, [gp(1, '2026-10-21T00:00:00'), gp(2, '2026-10-21T00:00:00')]),
        ist.RECENT_DECAYS_QUERY: (200, [gp(3, '2026-10-10T00:00:00', DECAY_DATE='2026-10-12')]),
    })
    changed, note = ist.runPass(db, fake, full=True)
    assert changed == 3
    assert '2 in catalogue' in note
    assert stored(db, 1, 'lastSeenFull') is not None
    assert stored(db, 3, 'lastSeenFull') is None
    assert stored(db, 3, 'decayDate') == '2026-10-12'
    assert not fake.loggedIn


def test_object_leaving_the_catalogue_counts_as_a_change(db):
    earlier = '2026-10-20T00:00:00Z'  # real timestamps: they are compared as text
    ist.storeEntries(db, [gp(1, '2026-10-20T00:00:00'), gp(2, '2026-10-20T00:00:00')], earlier, seenFull=earlier)
    fake = FakeSpaceTrack({
        ist.FULL_CATALOGUE_QUERY: (200, [gp(1, '2026-10-20T00:00:00')]),
        ist.RECENT_DECAYS_QUERY: (200, []),
    })
    changed, note = ist.runPass(db, fake, full=True)
    assert changed == 1
    assert '1 left the catalogue' in note
    assert stored(db, 2, 'lastSeenFull') == earlier


def test_recent_pass_uses_only_the_recent_query(db):
    fake = FakeSpaceTrack({ist.RECENT_ELEMENTS_QUERY: (200, [gp(1, '2026-10-21T00:00:00')])})
    changed, _ = ist.runPass(db, fake, full=False)
    assert changed == 1
    assert fake.queries == [ist.RECENT_ELEMENTS_QUERY]


def test_empty_catalogue_is_an_error_and_stores_nothing(db):
    fake = FakeSpaceTrack({ist.FULL_CATALOGUE_QUERY: (200, []), ist.RECENT_DECAYS_QUERY: (200, [])})
    with pytest.raises(Exception, match='empty catalogue'):
        ist.runPass(db, fake, full=True)
    assert db.execute('SELECT COUNT(*) FROM gp').fetchone()[0] == 0


def test_http_error_raises(db):
    fake = FakeSpaceTrack({ist.RECENT_ELEMENTS_QUERY: (500, {'error': 'x'})})
    with pytest.raises(Exception, match='HTTP 500'):
        ist.runPass(db, fake, full=False)


# --- Scheduling and run records ---------------------------------------------

def test_full_pass_due_with_no_history(db):
    assert ist.fullPassDue(db)


def test_full_pass_due_after_interval_only(db):
    recordRun(db, ist.FULL_JOB, 'x', True)
    finished = datetime.strptime(
        db.execute('SELECT finishedAt FROM ingestionRuns').fetchone()[0], '%Y-%m-%dT%H:%M:%SZ'
    ).replace(tzinfo=timezone.utc)
    assert not ist.fullPassDue(db, now=finished + timedelta(hours=12))
    assert ist.fullPassDue(db, now=finished + timedelta(hours=23))


def test_failed_full_pass_does_not_count(db):
    recordRun(db, ist.FULL_JOB, 'x', False)
    assert ist.fullPassDue(db)


def test_main_records_failure_without_credentials(tmp_path, monkeypatch):
    path = str(tmp_path / 'st.db')
    realOpenDb = ist.openDb
    monkeypatch.setattr(ist, 'openDb', lambda: realOpenDb(path))
    monkeypatch.setattr(ist, 'SpaceTrack', lambda: type('NoCreds', (), {'configured': False})())
    assert ist.main(['--recent']) == 1
    conn = sqlite3.connect(path)
    succeeded, note = conn.execute('SELECT succeeded, note FROM ingestionRuns').fetchone()
    assert succeeded == 0 and 'credentials' in note

