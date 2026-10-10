"""Tests for scripts/ingestGcat.py -- parsing GCAT's TSV conventions and
loading them, against sample lines in GCAT's real format and in-memory
databases only (no network).

Run with:  pytest 0_tests/ -v
"""

import os
import sqlite3
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import ingestGcat  # noqa: E402
from ingestGcat import parseTsv, parseVagueDate, replaceTable  # noqa: E402

T = '\t'

SATCAT = '\n'.join([
    '#JCAT\tSatcat\tLaunch_Tag\tPiece\tType\tName\tPLName\tLDate\tParent\tSDate\tPrimary\tDDate\tStatus\tDest'
    '\tOwner\tState\tManufacturer\tBus\tMotor\tMass\tMassFlag\tDryMass\tDryFlag\tTotMass\tTotFlag\tLength'
    '\tLFlag\tDiameter\tDFlag\tSpan\tSpanFlag\tShape\tODate\tPerigee\tPF\tApogee\tAF\tInc\tIF\tOpOrbit'
    '\tOQUAL\tAltNames',
    '# Updated 2026 Oct  8 2357:56',
    # Re-entered rocket stage: dropped.
    T.join(['S00001    ', '00001', '1957 ALP', '1957 ALP 1', 'R2          ', '8K71PS No. M1-10 Stage 2',
            '8K71A M1-10 (M1-1PS)', '1957 Oct  4', '-', '1957 Oct  4 1933', 'Earth', '1957 Dec  1 1000?',
            'R', '-', 'OKB1', 'SU', 'OKB1', 'Blok-A', '-', '    7790 ', ' ', '   7790 ', ' ', '    7800 ',
            '?', '  28.0 ', ' ', '  2.6 ', ' ', '   28.0 ', ' ', 'Cyl', '1957 Oct  4', '     214', ' ',
            '     938', ' ', ' 65.10 ', ' ', 'LLEO/I', '-', '-']),
    # Re-entered payload: kept (payloads are always kept).
    T.join(['S00004    ', '00004', '1958 ALP', '1958 ALP', 'P A         ', 'Explorer I', 'Explorer 1',
            '1958 Feb  1', 'A00004', '1958 Feb  1 0355', 'Earth', '1970 Mar 31 1045?', 'AR', '-',
            'ABMA/JPLA', 'US', 'JPLA', 'Explorer', '-', '       8 ', ' ', '      8 ', ' ', '      14 ', ' ',
            '   0.8 ', ' ', '  0.1 ', ' ', '    0.8 ', ' ', 'Cyl', '1958 Feb  1', '     359', ' ', '    2542',
            ' ', ' 33.18 ', ' ', 'LEO/I', '-', ':UA']),
    # Debris still in orbit: kept.
    T.join(['S99999    ', '99999', '2020-001', '2020-001X', 'D           ', 'Fragment', '-', '2020 Jan  7',
            '-', '-', 'Earth', '-', 'O', '-', 'SPX', 'US', '-', '-', '-', '-', ' ', '-', ' ', '-', ' ', '-',
            ' ', '-', ' ', '-', ' ', '-', '2026 Oct  1', '     540', ' ', '     560', ' ', ' 53.00 ', ' ',
            'LEO/I', '-', '-']),
])

PSATCAT = '\n'.join([
    '#JCAT\tPiece\tName\tLDate\tTLast\tTOp\tTDate\tTF\tProgram\tPlane\tAtt\tMvr\tClass\tCategory\tResult'
    '\tControl\tDiscipline\tUNState\tUNReg\tUNPeriod\tUNPerigee\tUNApogee\tUNInc\tDispEpoch\tDispPeri'
    '\tDispApo\tDispInc\tComment',
    '# Updated 2026 Oct  8 2358:02',
    T.join(['S00004    ', '1958 ALP', 'Explorer 1', '1958 Feb  1 ', '1958 Apr  1', '1958 Apr  1', '1958 Apr  1',
            '-', 'Explorer ABMA', '-', '-', '-', 'C', 'SCI', 'S', 'JPL', 'P*', 'US', 'A/AC.105/INF.001', '-',
            '-', '-', '-', '-', '       0', '       0', '  0.00 ', 'Discovered trapped radiation']),
])

ORGS = '\n'.join([
    '#Code\tUCode\tStateCode\tType\tClass\tTStart\tTStop\tShortName\tName\tLocation\tLongitude\tLatitude'
    '\tError\tParent\tShortEName\tEName\tUName',
    '# Updated 2026 Oct  8 2356:31',
    T.join(['SPX', 'SPX', 'US', 'LV/P', 'B', '2002', '-', 'SpaceX', 'Space Exploration Technologies',
            'Hawthorne', '-', '-', '0.0200 ', '-', 'SpaceX', 'Space Exploration Technologies', 'SpaceX']),
])

LAUNCHLOG = '\n'.join([
    '#Launch_Tag\tLaunch_Date\tPiece\tType\tName\tPLName\tJCAT\tSatOwner\tSatState\tLV_Type\tFlight_ID'
    '\tPlatform\tLaunch_Site\tLaunch_Pad\tAscent_Site\tAscent_Pad\tAgency\tLVState\tLaunch_Code\tLTCite',
    '# Updated 2026 Oct  8 2356:05',
    T.join(['1958 ALP  ', '1958 Feb  1 0347:56', '1958 ALP', 'P A         ', 'Explorer I', 'Explorer 1',
            'S00004    ', 'ABMA/JPLA', 'US', 'Jupiter C', 'RS-29    UE', '-', 'CC', 'LC26A', '-', '-', 'ABMA',
            'US', 'OS  ', 'JunoFam']),
])

FILES = {'cat/satcat.tsv': SATCAT, 'cat/psatcat.tsv': PSATCAT, 'tables/orgs.tsv': ORGS,
         'derived/launchlog.tsv': LAUNCHLOG}


# --- Parsing ------------------------------------------------------------------

@pytest.mark.parametrize('text, expected', [
    ('1957 Oct  4 1928:34', ('1957-10-04T19:28:34', False)),
    ('1957 Dec  1 1000?', ('1957-12-01T10:00', True)),
    ('1958 Jan  4?', ('1958-01-04', True)),
    ('1984 Mar', ('1984-03', False)),
    ('1984', ('1984', False)),
    ('2016 Jun  8 2359:57.345', ('2016-06-08T23:59:57', False)),
    ('-', (None, False)),
    ('', (None, False)),
    ('not a date', (None, False)),
])
def test_vague_dates(text, expected):
    assert parseVagueDate(text) == expected


def test_tsv_header_padding_and_nulls():
    rows = parseTsv(SATCAT)
    assert len(rows) == 3                       # both '#' lines skipped
    assert rows[0]['JCAT'] == 'S00001'          # padding stripped
    assert rows[0]['Parent'] is None            # '-' is null
    assert rows[0]['Type'] == 'R2'


# --- Row builders -------------------------------------------------------------

def test_objects_keep_payloads_and_in_orbit_only():
    rows = list(ingestGcat.objectRows(parseTsv(SATCAT)))
    assert [r[0] for r in rows] == ['S00004', 'S99999']   # re-entered stage dropped


def test_object_fields():
    explorer = next(ingestGcat.objectRows(parseTsv(SATCAT)))
    (jcat, norad, launchTag, _, satType, coarseType, _, _, launchDate, _, decayDate, decayUncertain,
     status, owners, ownerCode, stateCode, *_rest) = explorer
    assert (jcat, norad, launchTag, coarseType) == ('S00004', 4, '1958 ALP', 'P')
    assert satType == 'P A'
    assert (launchDate, decayDate, decayUncertain) == ('1958-02-01', '1970-03-31T10:45', 1)
    assert (status, owners, ownerCode, stateCode) == ('AR', 'ABMA/JPLA', 'ABMA', 'US')


def test_payload_class_and_launch_rows():
    [payload] = ingestGcat.payloadRows(parseTsv(PSATCAT))
    assert payload[0] == 'S00004' and payload[4] == 'C' and payload[5] == 'SCI'
    [launch] = ingestGcat.launchRows(parseTsv(LAUNCHLOG))
    assert launch[0] == '1958 ALP' and launch[3] == '1958-02-01T03:47:56' and launch[15] == 'OS'


# --- Loading ------------------------------------------------------------------

def test_replace_table_rolls_back_on_error():
    db = sqlite3.connect(':memory:')
    ingestGcat.ensureSchema(db)
    replaceTable(db, 'gcatOrgs', ingestGcat.orgRows(parseTsv(ORGS)))
    with pytest.raises(sqlite3.Error):
        replaceTable(db, 'gcatOrgs', [('X', 'X')])  # wrong column count
    assert db.execute('SELECT code FROM gcatOrgs').fetchall() == [('SPX',)]


def test_replace_table_refuses_to_empty():
    db = sqlite3.connect(':memory:')
    ingestGcat.ensureSchema(db)
    with pytest.raises(ValueError):
        replaceTable(db, 'gcatOrgs', [])


def test_full_run_loads_every_table(monkeypatch):
    monkeypatch.setattr(ingestGcat, 'fetchIfModified',
                        lambda db, path, force=False: (FILES[path], 'Thu, 08 Oct 2026 23:59:07 GMT'))
    db = sqlite3.connect(':memory:')
    assert ingestGcat.runGcatIngestion(db) == 2   # two new objects
    counts = {t: db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
              for t in ('gcatObjects', 'gcatPayloads', 'gcatOrgs', 'gcatLaunches', 'gcatFiles')}
    assert counts == {'gcatObjects': 2, 'gcatPayloads': 1, 'gcatOrgs': 1, 'gcatLaunches': 1, 'gcatFiles': 4}
    # Second run, nothing new.
    assert ingestGcat.runGcatIngestion(db) == 0


def test_unchanged_files_are_skipped(monkeypatch):
    monkeypatch.setattr(ingestGcat, 'fetchIfModified', lambda db, path, force=False: (None, None))
    db = sqlite3.connect(':memory:')
    assert ingestGcat.runGcatIngestion(db) == 0


def test_decay_summary_counts_by_year_type_and_status():
    rows = ingestGcat.decayRows([
        {'Type': 'P', 'Status': 'R', 'DDate': '2025 Mar  3', 'Owner': 'NASA'},
        {'Type': 'P', 'Status': 'R', 'DDate': '2025 Jun', 'Owner': 'SPXS'},
        {'Type': 'P', 'Status': 'R', 'DDate': '2025 Jul', 'Owner': 'ESA'},
        {'Type': 'R2', 'Status': 'R', 'DDate': '2025', 'Owner': 'SPX'},
        {'Type': 'P', 'Status': 'O', 'DDate': '-'},     # still in orbit: no decay date
    ])
    assert rows == [(2025, 'P', 'R', 0, 2), (2025, 'P', 'R', 1, 1), (2025, 'R', 'R', 1, 1)]


def test_unchanged_satcat_is_reloaded_while_the_decay_summary_is_empty(monkeypatch):
    forced = {}

    def fetch(db, path, force=False):
        forced[path] = force
        return None, None
    monkeypatch.setattr(ingestGcat, 'fetchIfModified', fetch)
    ingestGcat.runGcatIngestion(sqlite3.connect(':memory:'))
    assert forced['cat/satcat.tsv'] is True
    assert forced['cat/psatcat.tsv'] is False


def test_all_downloads_failing_raises(monkeypatch):
    def unreachable(db, path, force=False):
        raise urllib.error.URLError('connection refused')
    monkeypatch.setattr(ingestGcat, 'fetchIfModified', unreachable)
    with pytest.raises(RuntimeError):
        ingestGcat.runGcatIngestion(sqlite3.connect(':memory:'))
