"""Command-line tool for the project bug log, bugsDB.xlsx (sheet "bugsDB").

Edits the workbook in place with openpyxl, so its formatting, date formats
and drop-down validations survive: a new row copies its style from the row
above, and the allowed values for Status / Severity / Server / Phase /
Bug-or-Feature are read from the sheet's own drop-downs, so they stay in
step if those lists are changed in Excel.

Examples (from the project root):

    python 0_tools/bugs.py list                     # every bug
    python 0_tools/bugs.py list --open              # open ones only
    python 0_tools/bugs.py show 5                   # one bug in full
    python 0_tools/bugs.py add                      # prompts for each field
    python 0_tools/bugs.py add --title "Map won't zoom" --severity Medium \\
        --component "On-Orbit map" --actual "Zoom buttons do nothing"
    python 0_tools/bugs.py set 3 --fixed            # Status=Fixed, Date Fixed=today
    python 0_tools/bugs.py set 3 --reopen           # Status=Open, Date Fixed cleared
    python 0_tools/bugs.py set 3 --root-cause "..." --severity High
    python 0_tools/bugs.py import-reports --dry-run # tester reports, live + dev

Add --dry-run to add/set to see the result without saving. Every save first
copies the workbook to bugsDB.xlsx.bak. Close the workbook in Excel before
writing -- Excel locks the file.

Needs openpyxl (see requirements-dev.txt): python -m pip install openpyxl
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

try:
    import openpyxl
except ImportError:
    sys.exit('openpyxl is needed: python -m pip install openpyxl')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WORKBOOK = os.path.join(PROJECT_ROOT, 'bugsDB.xlsx')
SHEET = 'bugsDB'

# Command-line option -> column header in the sheet.
FIELDS = [
    ('title', 'Title'),
    ('status', 'Status'),
    ('severity', 'Severity'),
    ('component', 'Component'),
    ('description', 'Description'),
    ('steps', 'Steps to Reproduce'),
    ('expected', 'Expected Behaviour'),
    ('actual', 'Actual Behaviour'),
    ('root_cause', 'Root Cause'),
    ('found', 'Date Found'),
    ('server', 'Server'),
    ('found_by', 'Found By'),
    ('date_fixed', 'Date Fixed'),
    ('phase', 'Phase'),
    ('type', 'Bug / Feature Request'),
    ('notes', 'Notes'),
]
DATE_HEADERS = {'Date Found', 'Date Fixed'}
DEFAULTS = {
    'Status': 'Open',
    'Severity': 'Low',
    'Server': 'DEV',
    'Found By': 'Al',
    'Phase': 'Pre-Alpha',
    'Bug / Feature Request': 'Bug',
}


class BugLog:
    """The bugsDB sheet: header-to-column map, drop-down choices, rows."""

    def __init__(self, path):
        self.path = path
        self.workbook = openpyxl.load_workbook(path)
        self.sheet = self.workbook[SHEET]
        self.columns = {cell.value: cell.column for cell in self.sheet[1] if cell.value}
        missing = [header for _, header in FIELDS + [('id', 'ID')] if header not in self.columns]
        if missing:
            sys.exit(f'{path}: sheet "{SHEET}" has no column(s) {missing}')
        self.choices = self._readDropDownChoices()

    def _readDropDownChoices(self):
        letterToHeader = {
            openpyxl.utils.get_column_letter(column): header for header, column in self.columns.items()
        }
        choices = {}
        for validation in self.sheet.data_validations.dataValidation:
            if validation.type != 'list' or not validation.formula1:
                continue
            values = [v.strip() for v in validation.formula1.strip('"').split(',')]
            for cellRange in str(validation.sqref).split():
                letter = ''.join(ch for ch in cellRange.split(':')[0] if ch.isalpha())
                if letter in letterToHeader:
                    choices[letterToHeader[letter]] = values
        return choices

    def dataRows(self):
        idColumn = self.columns['ID']
        return [row for row in range(2, self.sheet.max_row + 1)
                if self.sheet.cell(row, idColumn).value not in (None, '')]

    def get(self, row, header):
        return self.sheet.cell(row, self.columns[header]).value

    def set(self, row, header, value):
        self.sheet.cell(row, self.columns[header]).value = value

    def rowForID(self, bugID):
        for row in self.dataRows():
            if str(self.get(row, 'ID')) == str(bugID):
                return row
        sys.exit(f'No bug with ID {bugID}.')

    def nextID(self):
        ids = [int(self.get(row, 'ID')) for row in self.dataRows() if str(self.get(row, 'ID')).isdigit()]
        return max(ids, default=0) + 1

    def appendRow(self, values):
        """Writes `values` ({header: value}) to the row after the last bug,
        copying that row's cell styles and height."""
        rows = self.dataRows()
        template = rows[-1] if rows else None
        newRow = (template or 1) + 1
        for header, column in self.columns.items():
            cell = self.sheet.cell(newRow, column)
            if template is not None and self.sheet.cell(template, column).has_style:
                cell._style = self.sheet.cell(template, column)._style
            cell.value = values.get(header)
        if template is not None and self.sheet.row_dimensions[template].height:
            self.sheet.row_dimensions[newRow].height = self.sheet.row_dimensions[template].height
        return newRow

    def save(self):
        shutil.copy2(self.path, self.path + '.bak')
        try:
            self.workbook.save(self.path)
        except PermissionError:
            sys.exit(f'Could not save {self.path} -- is it open in Excel? Close it and try again.')


# --- Value checking ---------------------------------------------------------

def parseDate(text):
    """'today', 'none' (clears) or YYYY-MM-DD."""
    if text is None:
        return None
    if text.lower() == 'today':
        return datetime.datetime.combine(datetime.date.today(), datetime.time())
    if text.lower() in ('none', 'clear', ''):
        return ''
    try:
        return datetime.datetime.strptime(text, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError(f'"{text}" is not a date -- use YYYY-MM-DD or "today"')


def checkChoice(log, header, value):
    """Matches `value` case-insensitively against the column's drop-down,
    returning the drop-down's own spelling."""
    allowed = log.choices.get(header)
    if value in (None, '') or not allowed:
        return value
    for option in allowed:
        if option.lower() == str(value).lower():
            return option
    sys.exit(f'{header} must be one of: {", ".join(allowed)} (got "{value}")')


# --- Output -------------------------------------------------------------------

def formatValue(value):
    if isinstance(value, datetime.datetime):
        return value.strftime('%Y-%m-%d')
    return '' if value is None else str(value)


def printBug(log, row):
    width = max(len(header) for header in log.columns)
    for header in log.columns:
        print(f'{header:>{width}} : {formatValue(log.get(row, header))}')


# --- Subcommands ------------------------------------------------------------

def commandList(log, args):
    rows = log.dataRows()
    if args.open:
        rows = [row for row in rows if str(log.get(row, 'Status')).lower() == 'open']
    if args.severity:
        rows = [row for row in rows if str(log.get(row, 'Severity')).lower() == args.severity.lower()]
    if args.type:
        rows = [row for row in rows if str(log.get(row, 'Bug / Feature Request')).lower() == args.type.lower()]
    if not rows:
        print('No matching bugs.')
        return
    print(f'{"ID":>3}  {"STATUS":<6}  {"SEVERITY":<8}  {"FOUND":<10}  TITLE')
    for row in rows:
        title = formatValue(log.get(row, 'Title'))
        if len(title) > 70:
            title = title[:67] + '...'
        print(f'{formatValue(log.get(row, "ID")):>3}  {formatValue(log.get(row, "Status")):<6}  '
              f'{formatValue(log.get(row, "Severity")):<8}  {formatValue(log.get(row, "Date Found")):<10}  {title}')
    print(f'\n{len(rows)} bug(s).')


def commandShow(log, args):
    printBug(log, log.rowForID(args.id))


def prompt(log, header, default=None):
    choices = log.choices.get(header)
    hint = f' [{"/".join(choices)}]' if choices else ''
    hint += f' (default: {formatValue(default)})' if default not in (None, '') else ''
    if header in DATE_HEADERS:
        hint += ' (YYYY-MM-DD or "today")'
    while True:
        answer = input(f'{header}{hint}: ').strip()
        if not answer:
            return default
        if header in DATE_HEADERS:
            try:
                return parseDate(answer)
            except argparse.ArgumentTypeError as error:
                print(error)
                continue
        if choices and answer.lower() not in (c.lower() for c in choices):
            print(f'  Choose one of: {", ".join(choices)}')
            continue
        return checkChoice(log, header, answer)


def commandAdd(log, args):
    supplied = {header: getattr(args, option) for option, header in FIELDS}
    interactive = supplied['Title'] is None
    if interactive:
        print('New bug -- press Enter to accept a default or leave a field blank.\n')

    values = {'ID': log.nextID()}
    for option, header in FIELDS:
        default = DEFAULTS.get(header)
        if header == 'Date Found':
            default = parseDate('today')
        value = supplied[header]
        if interactive and value is None:
            if header == 'Date Fixed' and str(values.get('Status')).lower() != 'fixed':
                value = None
            else:
                value = prompt(log, header, default)
        elif value is None:
            value = default
        values[header] = checkChoice(log, header, value)

    if not values['Title']:
        sys.exit('A title is required.')
    if str(values['Status']).lower() == 'fixed' and not values.get('Date Fixed'):
        values['Date Fixed'] = parseDate('today')

    row = log.appendRow(values)
    print()
    printBug(log, row)
    if args.dry_run:
        print('\nDRY RUN -- not saved.')
        return
    log.save()
    print(f'\nAdded bug {values["ID"]} to {log.path}')


def commandSet(log, args):
    row = log.rowForID(args.id)
    changes = {}
    for option, header in FIELDS:
        value = getattr(args, option, None)
        if value is not None:
            changes[header] = checkChoice(log, header, value)
    if args.fixed:
        changes['Status'] = checkChoice(log, 'Status', 'Fixed')
        changes.setdefault('Date Fixed', parseDate('today'))
    if args.reopen:
        changes['Status'] = checkChoice(log, 'Status', 'Open')
        changes['Date Fixed'] = ''
    if not changes:
        sys.exit('Nothing to change -- give at least one field option, --fixed or --reopen.')

    for header, value in changes.items():
        before = formatValue(log.get(row, header))
        log.set(row, header, value if value != '' else None)
        print(f'{header}: "{before}" -> "{formatValue(log.get(row, header))}"')
    if args.dry_run:
        print('\nDRY RUN -- not saved.')
        return
    log.save()
    print(f'\nUpdated bug {args.id} in {log.path}')


# --- Tester reports -----------------------------------------------------------
# The BUG REPORT form (assets/bugReport.js -> /api/bug-report in server.py)
# appends to inboxBugReports.db in the database folder (scripts/dbPaths.py) on
# whichever server it was used on:
# the live site's (server LIVE) or a local dev server's (server DEV).
# import-reports copies every report not yet copied from both into the
# workbook, oldest first. Each imported row's Notes carries the key
# "[report LIVE#12]" (server + report id), so a report can never be
# imported twice even if marking it copied at the source fails; marking
# (copiedToBugsDb = 1) just keeps the next fetch small. The live database
# is read over SSH; nothing is downloaded or stored locally.

sys.path.append(os.path.join(PROJECT_ROOT, 'scripts'))
import dbPaths  # noqa: E402

DEV_REPORTS_DB = dbPaths.dbPath(dbPaths.BUG_REPORTS_DB)
LIVE_SSH = ['ssh', '-i', os.path.expanduser('~/.ssh/godaddy_lcars_fas'), '-o', 'BatchMode=yes',
            '-o', 'ConnectTimeout=30', 'sip9rb1lekyg@gaps2024.com']
LIVE_PYTHON = '/home/sip9rb1lekyg/virtualenv/public_html/LCARS-FAS/3.9/bin/python'
# Candidates in order; the live server uses the first whose folder exists:
# databases/inboxBugReports.db once migrated, ingestionDBs/bugReports.db
# before (see dbPaths.py).
LIVE_REPORTS_DBS = [f'{dbPaths.LIVE_DB_DIRS[0]}/{dbPaths.BUG_REPORTS_DB}',
                    f'{dbPaths.LIVE_DB_DIRS[1]}/{dbPaths.LEGACY_NAMES[dbPaths.BUG_REPORTS_DB]}']
REPORT_KEY = re.compile(r'\[report (LIVE|DEV)#(\d+)\]')

FETCH_SQL = 'SELECT * FROM bugReports WHERE copiedToBugsDb = 0 ORDER BY id'
MARK_SQL = 'UPDATE bugReports SET copiedToBugsDb = 1 WHERE id IN ({})'

# Run by the live server's Python, fed in over SSH's stdin.
REMOTE_FETCH = '''
import json, os, sqlite3
paths = {paths!r}
path = next((p for p in paths if os.path.isdir(os.path.dirname(p))), paths[-1])
if not os.path.exists(path):
    print('[]')
else:
    db = sqlite3.connect('file:' + path + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    print(json.dumps([dict(row) for row in db.execute({sql!r})]))
'''
REMOTE_MARK = '''
import os, sqlite3
paths = {paths!r}
path = next((p for p in paths if os.path.isdir(os.path.dirname(p))), paths[-1])
db = sqlite3.connect(path)
db.execute({sql!r}, {ids!r})
db.commit()
print('marked', db.total_changes)
'''


def runOnLive(script):
    result = subprocess.run(LIVE_SSH + [LIVE_PYTHON, '-'], input=script, capture_output=True,
                            text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f'live server: {result.stderr.strip()[-300:]}')
    return result.stdout


def fetchReports(source):
    """Uncopied reports from 'DEV' (this machine) or 'LIVE' (over SSH)."""
    if source == 'DEV':
        if not os.path.exists(DEV_REPORTS_DB):
            return []
        db = sqlite3.connect(f'file:{DEV_REPORTS_DB}?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in db.execute(FETCH_SQL)]
        finally:
            db.close()
    return json.loads(runOnLive(REMOTE_FETCH.format(paths=LIVE_REPORTS_DBS, sql=FETCH_SQL)))


def markReportsCopied(source, ids):
    if not ids:
        return
    sql = MARK_SQL.format(','.join('?' * len(ids)))
    if source == 'DEV':
        db = sqlite3.connect(DEV_REPORTS_DB)
        try:
            db.execute(sql, ids)
            db.commit()
        finally:
            db.close()
    else:
        runOnLive(REMOTE_MARK.format(paths=LIVE_REPORTS_DBS, sql=sql, ids=list(ids)))


def reportToBug(log, report, bugID):
    """One bugReports row -> one bugsDB row ({header: value}). The source
    server comes from the database the report was read from, and the DTG
    (UTC, as recorded by the server on receipt) goes into Date Found and,
    in full, into Notes."""
    found = datetime.datetime.fromisoformat(report['dateFound']).astimezone(datetime.timezone.utc)
    notes = [f'[report {report["server"]}#{report["id"]}]',
             f'Tester report, DTG {found.strftime("%Y-%m-%d %H:%M:%SZ")}, {report["server"]} server']
    if report.get('viewport'):
        notes.append(f'viewport {report["viewport"]}')
    if report.get('userAgent'):
        notes.append(f'browser: {report["userAgent"]}')
    return {
        'ID': bugID,
        'Title': report['title'],
        'Status': checkChoice(log, 'Status', 'Open'),
        'Severity': checkChoice(log, 'Severity', report['severity']),
        'Component': report['component'],
        'Description': report['description'],
        'Steps to Reproduce': report.get('stepsToReproduce'),
        'Expected Behaviour': report.get('expectedBehaviour'),
        'Actual Behaviour': report.get('actualBehaviour'),
        'Date Found': found.replace(tzinfo=None),
        'Server': checkChoice(log, 'Server', report['server']),
        'Found By': report.get('foundBy') or 'Anonymous tester',
        'Phase': checkChoice(log, 'Phase', report.get('phase') or 'Alpha'),
        'Bug / Feature Request': checkChoice(log, 'Bug / Feature Request', report['bugOrFeature']),
        'Notes': '; '.join(notes),
    }


def commandImportReports(log, args):
    sources = ['LIVE', 'DEV'] if args.source == 'both' else [args.source.upper()]
    already = {match.groups() for row in log.dataRows()
               for match in [REPORT_KEY.search(str(log.get(row, 'Notes') or ''))] if match}

    pending = []  # (source, report)
    for source in sources:
        try:
            reports = fetchReports(source)
        except Exception as error:
            print(f'{source}: could not read reports ({error}) -- skipped')
            continue
        fresh = [r for r in reports if (r['server'], str(r['id'])) not in already]
        print(f'{source}: {len(reports)} uncopied report(s), {len(fresh)} new to the workbook')
        pending += [(source, r) for r in fresh]
        # Reports already in the workbook but not yet marked: mark them now.
        stale = [r['id'] for r in reports if (r['server'], str(r['id'])) in already]
        if stale and not args.dry_run:
            markReportsCopied(source, stale)

    if not pending:
        print('Nothing to import.')
        return
    pending.sort(key=lambda item: item[1]['dateFound'])
    nextID = log.nextID()
    for source, report in pending:
        row = log.appendRow(reportToBug(log, report, nextID))
        print(f'  bug {nextID}: {report["server"]}#{report["id"]} {report["dateFound"]} {report["title"]}')
        nextID += 1
    if args.dry_run:
        print(f'\nDRY RUN -- {len(pending)} report(s) not saved or marked.')
        return
    log.save()
    print(f'\nImported {len(pending)} report(s) into {log.path}')
    for source in sources:
        ids = [r['id'] for s, r in pending if s == source]
        try:
            markReportsCopied(source, ids)
        except Exception as error:
            print(f'{source}: imported, but could not mark them copied ({error}); '
                  'the next run will recognise them and skip them.')


# --- Command line -----------------------------------------------------------

def addFieldOptions(parser, forAdd):
    group = parser.add_argument_group('fields' if forAdd else 'fields to change')
    group.add_argument('--title', help='short summary (required unless prompting)' if forAdd else None)
    group.add_argument('--status', help='Open / Fixed' + (' (default Open)' if forAdd else ''))
    group.add_argument('--severity', help='Low / Medium / High' + (' (default Low)' if forAdd else ''))
    group.add_argument('--component', help='where it is, e.g. "On-Orbit — assets/onOrbitPanel.js"')
    group.add_argument('--description')
    group.add_argument('--steps', help='steps to reproduce')
    group.add_argument('--expected', help='expected behaviour')
    group.add_argument('--actual', help='actual behaviour')
    group.add_argument('--root-cause', dest='root_cause')
    group.add_argument('--found', type=parseDate, help='date found, YYYY-MM-DD or "today"'
                       + (' (default today)' if forAdd else ''))
    group.add_argument('--server', help='DEV / LIVE -- which server it was found on'
                       + (' (default DEV)' if forAdd else ''))
    group.add_argument('--found-by', dest='found_by', help='who found it' + (' (default Al)' if forAdd else ''))
    group.add_argument('--date-fixed', dest='date_fixed', type=parseDate,
                       help='YYYY-MM-DD, "today", or "none" to clear')
    group.add_argument('--phase', help='Pre-Alpha / Alpha / Beta' + (' (default Pre-Alpha)' if forAdd else ''))
    group.add_argument('--type', help='Bug / Feature-Request' + (' (default Bug)' if forAdd else ''))
    group.add_argument('--notes', help='anything else, e.g. what a partial fix left to do')


def buildParser():
    parser = argparse.ArgumentParser(
        description='List, show, add and update bugs in the project bug log (bugsDB.xlsx).',
        epilog='Run "python 0_tools/bugs.py <command> --help" for each command\'s options.')
    parser.add_argument('--file', default=DEFAULT_WORKBOOK, help='workbook to use (default: bugsDB.xlsx in the project root)')
    commands = parser.add_subparsers(dest='command', required=True, metavar='command')

    listParser = commands.add_parser('list', help='list bugs, one line each')
    listParser.add_argument('--open', action='store_true', help='open bugs only')
    listParser.add_argument('--severity', help='only this severity')
    listParser.add_argument('--type', help='only Bug or Feature-Request')
    listParser.set_defaults(handler=commandList)

    showParser = commands.add_parser('show', help='show one bug in full')
    showParser.add_argument('id', help='bug ID')
    showParser.set_defaults(handler=commandShow)

    addParser = commands.add_parser(
        'add', help='add a bug (prompts for each field if --title is not given)',
        description='Add a bug. With no --title, prompts for every field in turn; otherwise uses the '
                    'options given plus defaults. The ID is assigned automatically.')
    addFieldOptions(addParser, forAdd=True)
    addParser.add_argument('--dry-run', action='store_true', help='show the new row without saving')
    addParser.set_defaults(handler=commandAdd)

    setParser = commands.add_parser('set', help='change fields of an existing bug')
    setParser.add_argument('id', help='bug ID')
    addFieldOptions(setParser, forAdd=False)
    shortcuts = setParser.add_mutually_exclusive_group()
    shortcuts.add_argument('--fixed', action='store_true', help='Status=Fixed and Date Fixed=today (unless --date-fixed given)')
    shortcuts.add_argument('--reopen', action='store_true', help='Status=Open and clear Date Fixed')
    setParser.add_argument('--dry-run', action='store_true', help='show the changes without saving')
    setParser.set_defaults(handler=commandSet)

    importParser = commands.add_parser(
        'import-reports', help='copy tester bug reports (BUG REPORT form) from the live and dev servers',
        description='Copy every tester report not yet copied from the live server (over SSH) and this '
                    "machine's dev server into the workbook, oldest first, as new Open bugs. Each one keeps "
                    'its source server and DTG; its Notes carry a [report LIVE#n] key so it is never '
                    'imported twice.')
    importParser.add_argument('--source', choices=['both', 'live', 'dev'], default='both',
                              help='which server(s) to read (default both)')
    importParser.add_argument('--dry-run', action='store_true', help='show what would be imported without saving')
    importParser.set_defaults(handler=commandImportReports)
    return parser


def main(argv=None):
    # Titles may contain characters the Windows console's code page can't
    # print; replace them rather than crash.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    args = buildParser().parse_args(argv)
    if not os.path.exists(args.file):
        sys.exit(f'No workbook at {args.file}')
    args.handler(BugLog(args.file), args)


if __name__ == '__main__':
    main()
