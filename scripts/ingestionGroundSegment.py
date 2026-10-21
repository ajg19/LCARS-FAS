"""Ground segment ingestion: builds databases/ingestionGroundSegment.db
(table ground_segment_assets) from Al's master spreadsheet,
grndSgmntAssets_master.xlsx.

Moved into the repo at step 8 of 0_documentation/dbRefactorPlan.md, from
DEV/LCARS/rschGrdSgmt/build_ground_segment_db.py. Under decision D this
database is built on the laptop, committed, and carried to the live
server by the deploy; the server never needs the spreadsheet or
openpyxl.

    python scripts/ingestionGroundSegment.py [path/to/workbook.xlsx]

The spreadsheet is the source of truth and is only ever read -- opened
read-only, never saved. It stays where Al keeps it
(DEV/LCARS/rschGrdSgmt/, outside this repo), which is the default path.
Every run rebuilds the table completely into a temporary file and then
swaps it into place, so a failed run leaves the previous database
untouched.

The sheet is selected by name ("Sheet1"), not position: the workbook also
has a pivot/summary sheet. Latitude/Longitude are converted from the
spreadsheet's "12.0464° S" text into signed decimal degrees. Every other
category-specific field stays TEXT, because the spreadsheet uses the
literal "N/A" wherever a field doesn't apply to an asset's type. Table
and column names are unchanged from the original build: the ground
segment panel reads them as they are.
"""

import argparse
import os
import re
import sqlite3
import sys

import openpyxl

from dbPaths import GROUND_SEGMENT_DB, ROOT, dbPath

DEFAULT_XLSX_PATH = os.path.join(os.path.dirname(ROOT), 'LCARS', 'rschGrdSgmt', 'grndSgmntAssets_master.xlsx')
SHEET = 'Sheet1'

COORD_RE = re.compile(r'^([\d.]+)\s*°?\s*([NSEW])$', re.IGNORECASE)

# Spreadsheet column -> table column, in table order (after id).
COLUMNS = (
    ('Type', 'type'), ('Name', 'name'), ('Operator(s)', 'operators'), ('ISO Code', 'iso_code'),
    ('Public / Private', 'public_private'), ('Latitude', 'latitude'), ('Longitude', 'longitude'),
    ('Diameter (m)', 'diameter_m'), ('# Missions', 'missions_count'),
    ('Sub-orbital Launches', 'suborbital_launches'), ('Orbital Launches', 'orbital_launches'),
    ('Active?', 'active'), ('Primary Focus', 'primary_focus'), ('Primary Function', 'primary_function'),
    ('Sensor Type / Aperture', 'sensor_type'), ('Number of Dishes', 'number_of_dishes'),
    ('Number of Sites', 'number_of_sites'), ('Description', 'description'),
)

CREATE_SQL = '''
    CREATE TABLE ground_segment_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        operators TEXT,
        iso_code TEXT,
        public_private TEXT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        diameter_m TEXT,
        missions_count TEXT,
        suborbital_launches TEXT,
        orbital_launches TEXT,
        active TEXT,
        primary_focus TEXT,
        primary_function TEXT,
        sensor_type TEXT,
        number_of_dishes TEXT,
        number_of_sites TEXT,
        description TEXT
    )
'''


def parseCoordinate(text):
    match = COORD_RE.match(str(text).strip())
    if not match:
        raise ValueError(f'Unrecognised coordinate format: {text!r}')
    value = float(match.group(1))
    return -value if match.group(2).upper() in ('S', 'W') else value


def loadRows(xlsxPath):
    """The data sheet's rows as dicts keyed by header. Read-only: the
    workbook is never modified or saved."""
    workbook = openpyxl.load_workbook(xlsxPath, read_only=True, data_only=True)
    try:
        rows = list(workbook[SHEET].iter_rows(values_only=True))
    finally:
        workbook.close()
    header, data = rows[0], rows[1:]
    return [dict(zip(header, row)) for row in data if any(cell is not None for cell in row)]


def assetValues(row):
    values = []
    for heading, column in COLUMNS:
        if column in ('latitude', 'longitude'):
            values.append(parseCoordinate(row[heading]))
        else:
            values.append(row.get(heading, 'N/A'))
    return values


def build(rows, path):
    """Writes the table into a fresh file at path + '.tmp', then swaps it
    in. Returns the number of rows."""
    tmp = path + '.tmp'
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    try:
        db.execute(CREATE_SQL)
        db.executemany(
            f'INSERT INTO ground_segment_assets ({", ".join(c for _, c in COLUMNS)}) '
            f'VALUES ({", ".join("?" * len(COLUMNS))})',
            [assetValues(row) for row in rows])
        db.commit()
        count = db.execute('SELECT COUNT(*) FROM ground_segment_assets').fetchone()[0]
    finally:
        db.close()
    os.replace(tmp, path)
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build ingestionGroundSegment.db from the master spreadsheet.')
    parser.add_argument('xlsx', nargs='?', default=DEFAULT_XLSX_PATH, help='workbook (default: the master)')
    args = parser.parse_args(argv)
    if not os.path.isfile(args.xlsx):
        raise SystemExit(f'ERROR: {args.xlsx} not found.')
    rows = loadRows(args.xlsx)
    path = dbPath(GROUND_SEGMENT_DB)
    count = build(rows, path)
    print(f'{count} assets from {os.path.basename(args.xlsx)} -> {path}')
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    for kind, n in db.execute('SELECT type, COUNT(*) FROM ground_segment_assets GROUP BY type ORDER BY 2 DESC'):
        print(f'  {kind}: {n}')
    db.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
