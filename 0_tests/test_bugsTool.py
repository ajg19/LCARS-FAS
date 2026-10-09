"""Tests for 0_tools/bugs.py -- always against a temporary copy of
bugsDB.xlsx, never the real one.

Run with:  pytest 0_tests/ -v
"""

import os
import shutil
import sys

import openpyxl
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, '0_tools'))
import bugs  # noqa: E402


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / 'bugsDB.xlsx'
    shutil.copy(os.path.join(PROJECT_ROOT, 'bugsDB.xlsx'), path)
    return str(path)


def run(workbook, *argv):
    bugs.main(['--file', workbook, *argv])


def lastBug(workbook):
    log = bugs.BugLog(workbook)
    row = log.dataRows()[-1]
    return log, row


def test_drop_down_choices_are_read_from_the_sheet(workbook):
    log = bugs.BugLog(workbook)
    assert log.choices['Status'] == ['Open', 'Fixed']
    assert log.choices['Severity'] == ['Low', 'Medium', 'High']
    assert log.choices['Server'] == ['DEV', 'LIVE']


def test_add_assigns_next_id_defaults_and_template_style(workbook):
    before = bugs.BugLog(workbook)
    expectedID = before.nextID()
    templateRow = before.dataRows()[-1]

    run(workbook, 'add', '--title', 'Test bug', '--severity', 'medium', '--actual', 'Broken')

    log, row = lastBug(workbook)
    assert log.get(row, 'ID') == expectedID
    assert log.get(row, 'Title') == 'Test bug'
    assert log.get(row, 'Severity') == 'Medium'  # normalised to the drop-down's spelling
    assert log.get(row, 'Status') == 'Open'
    assert log.get(row, 'Bug / Feature Request') == 'Bug'
    assert log.get(row, 'Server') == 'DEV'
    assert log.get(row, 'Date Found') is not None
    dateColumn = log.columns['Date Found']
    assert log.sheet.cell(row, dateColumn).number_format == log.sheet.cell(templateRow, dateColumn).number_format
    assert os.path.exists(workbook + '.bak')


def test_add_live_server(workbook):
    run(workbook, 'add', '--title', 'Seen on live', '--server', 'live')
    log, row = lastBug(workbook)
    assert log.get(row, 'Server') == 'LIVE'


def test_add_fixed_sets_date_fixed(workbook):
    run(workbook, 'add', '--title', 'Already fixed', '--status', 'Fixed')
    log, row = lastBug(workbook)
    assert log.get(row, 'Status') == 'Fixed'
    assert log.get(row, 'Date Fixed') is not None


def test_add_rejects_a_value_not_in_the_drop_down(workbook):
    with pytest.raises(SystemExit):
        run(workbook, 'add', '--title', 'Bad', '--severity', 'Catastrophic')


def test_add_dry_run_does_not_save(workbook):
    count = len(bugs.BugLog(workbook).dataRows())
    run(workbook, 'add', '--title', 'Not saved', '--dry-run')
    assert len(bugs.BugLog(workbook).dataRows()) == count


def test_add_prompts_when_no_title_given(workbook, monkeypatch):
    answers = iter(['Prompted bug', '', 'High'] + [''] * 20)
    monkeypatch.setattr('builtins.input', lambda prompt='': next(answers))
    run(workbook, 'add')
    log, row = lastBug(workbook)
    assert log.get(row, 'Title') == 'Prompted bug'
    assert log.get(row, 'Status') == 'Open'
    assert log.get(row, 'Severity') == 'High'


def test_set_fixed_and_reopen(workbook):
    run(workbook, 'add', '--title', 'To fix')
    log, row = lastBug(workbook)
    bugID = str(log.get(row, 'ID'))

    run(workbook, 'set', bugID, '--fixed')
    log, row = lastBug(workbook)
    assert log.get(row, 'Status') == 'Fixed'
    assert log.get(row, 'Date Fixed') is not None

    run(workbook, 'set', bugID, '--reopen')
    log, row = lastBug(workbook)
    assert log.get(row, 'Status') == 'Open'
    assert log.get(row, 'Date Fixed') is None


def test_set_unknown_id_exits(workbook):
    with pytest.raises(SystemExit):
        run(workbook, 'set', '9999', '--fixed')


def test_validations_and_other_sheets_survive_a_save(workbook):
    before = openpyxl.load_workbook(workbook)
    validations = len(before['bugsDB'].data_validations.dataValidation)
    run(workbook, 'add', '--title', 'Check survival')
    after = openpyxl.load_workbook(workbook)
    assert after.sheetnames == before.sheetnames
    assert len(after['bugsDB'].data_validations.dataValidation) == validations
