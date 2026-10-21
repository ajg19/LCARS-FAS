"""Server side script loading Jonathan McDowell's General Catalog of
Artificial Space Objects (GCAT) into databases/ingestionGCAT.db.

One weekly download serving two sections:
  * Launches -- which payloads flew on which launch (GCAT's launch log),
    to be matched later against Launch Library 2, which has no payloads.
  * The on-orbit overview -- each object's owner, country and sector:
    GCAT classes organisations, and individual payloads, as
        A  academic / amateur / non-profit
        B  business / commercial
        C  civil government
        D  defence / military / intelligence
    A payload's own class is "usually the same as the class of the owner
    organization, but not always" (GCAT documentation), so sector comes
    from the payload's class first and its owner's class as a fallback.

Four public files, no credentials (CC-BY-4.0 -- cite as "data from GCAT
(J. McDowell, planet4589.org/space/gcat)"), ~30 MB in all, updated by
GCAT nightly:

    cat/satcat.tsv         every catalogued object      -> gcatObjects
    cat/psatcat.tsv        payload details and class    -> gcatPayloads
    tables/orgs.tsv        organisations and class      -> gcatOrgs
    derived/launchlog.tsv  launches, one row per payload -> gcatLaunches

Each file is requested with If-Modified-Since, so an unchanged file is
neither downloaded again nor reloaded. A changed file replaces its table
whole inside one transaction, so the website never reads a half-loaded
table. The run is recorded in ingestionRuns (scripts/ingestionLog.py) for
the landing page's data-freshness table.

GCAT conventions handled here (see planet4589.org/space/gcat/web/intro/):
  * the first line is '#'-prefixed column names, the second '# Updated ...'
  * fields are space-padded; '-' (or empty) means null
  * dates are "Vague Dates": year, then optionally month, day and time
    ("1957 Oct  4 1928:34"), with a trailing '?' marking uncertainty --
    stored as ISO to the precision given (e.g. '1957-10', '1957-10-04T19:28'),
    with the original text alongside
  * Type (SatType) byte 1 is the coarse type: P payload, C component,
    R rocket stage, D fragmentation debris, S suborbital payload,
    X deleted entry, Z spurious entry

Run once and exit -- cron owns the (weekly) schedule. Run by hand from the
project root:  python scripts/ingestGcat.py
"""

import re
import socket
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from ingestionLog import trackRun

from dbPaths import GCAT_DB, dbPath
DB_PATH = dbPath(GCAT_DB)

GCAT_BASE_URL = 'https://planet4589.org/space/gcat/tsv/'
USER_AGENT = 'LCARS-FAS/1.0 (GCAT ingestion; +https://github.com/ajg19/LCARS-FAS)'
HTTP_TIMEOUT_SEC = 120   # satcat.tsv is ~19 MB

# Objects still in orbit, by GCAT Status code: O in orbit, OX in orbit but
# no recent tracking, AO attached in orbit, AO IN attached inside.
IN_ORBIT_STATUSES = {'O', 'OX', 'AO', 'AO IN'}

MONTHS = {m: i for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], start=1)}
VAGUE_DATE = re.compile(
    r'^(?P<year>\d{4})'
    r'(?:\s+(?P<month>[A-Z][a-z]{2}))?'
    r'(?:\s+(?P<day>\d{1,2}))?'
    r'(?:\s+(?P<hour>\d{2})(?P<minute>\d{2})?(?::(?P<second>\d{2})(?:\.\d+)?)?h?)?'
    r'\s*(?P<uncertain>\?)?$')


# --- Parsing ------------------------------------------------------------------

def nullable(value):
    value = (value or '').strip()
    return None if value in ('', '-') else value


def toFloat(value):
    value = nullable(value)
    if value is None:
        return None
    try:
        return float(value.rstrip('?'))
    except ValueError:
        return None


def parseVagueDate(text):
    """GCAT Vague Date -> (ISO string to the precision given, uncertain?).
    (None, False) for null or unrecognised text."""
    text = nullable(text)
    if text is None:
        return None, False
    match = VAGUE_DATE.match(text)
    if not match or (match['month'] and match['month'] not in MONTHS):
        return None, False
    iso = match['year']
    if match['month']:
        iso += f'-{MONTHS[match["month"]]:02d}'
        if match['day']:
            iso += f'-{int(match["day"]):02d}'
            if match['hour']:
                iso += f'T{match["hour"]}:{match["minute"] or "00"}'
                if match['second']:
                    iso += f':{match["second"]}'
    return iso, bool(match['uncertain'])


def parseTsv(text):
    """GCAT TSV text -> list of {column: stripped value or None} dicts."""
    columns = None
    rows = []
    for line in text.splitlines():
        if line.startswith('#'):
            if columns is None:
                columns = [c.strip() for c in line[1:].split('\t')]
            continue
        if not line.strip() or columns is None:
            continue
        fields = line.split('\t')
        fields += [''] * (len(columns) - len(fields))
        rows.append({name: nullable(value) for name, value in zip(columns, fields)})
    return rows


def noradNumber(value):
    return int(value) if value and value.isdigit() else None


# --- Row builders -------------------------------------------------------------

def objectRows(satcatRows):
    """Every payload, plus anything else still in orbit -- the ~40,000
    rocket stages and debris that have re-entered are left out."""
    for r in satcatRows:
        satType = r.get('Type') or ''
        coarseType = satType[:1] or None
        status = r.get('Status')
        if coarseType != 'P' and status not in IN_ORBIT_STATUSES:
            continue
        launchDate, _ = parseVagueDate(r.get('LDate'))
        decayDate, decayUncertain = parseVagueDate(r.get('DDate'))
        owners = (r.get('Owner') or '').split('/')
        yield (
            r['JCAT'], noradNumber(r.get('Satcat')), r.get('Launch_Tag'), r.get('Piece'),
            satType, coarseType, r.get('Name'), r.get('PLName'), launchDate, r.get('LDate'),
            decayDate, int(decayUncertain), status, r.get('Owner'), nullable(owners[0]),
            r.get('State'), r.get('Manufacturer'), r.get('Bus'), toFloat(r.get('Mass')),
            toFloat(r.get('Perigee')), toFloat(r.get('Apogee')), toFloat(r.get('Inc')),
            r.get('OpOrbit'), nullable(r.get('Parent')),
            # Physical size in metres (GCAT Length, Diameter, Span -- span
            # being the largest dimension across, e.g. solar arrays out) and
            # Shape (e.g. 'Cyl', 'Box', 'Sphere'): for estimating brightness.
            toFloat(r.get('Length')), toFloat(r.get('Diameter')), toFloat(r.get('Span')),
            nullable(r.get('Shape')),
        )


def payloadRows(psatcatRows):
    for r in psatcatRows:
        yield (
            r['JCAT'], r.get('Piece'), r.get('Name'), r.get('Program'), r.get('Class'),
            r.get('Category'), r.get('Result'), r.get('Control'), r.get('Discipline'),
            parseVagueDate(r.get('TLast'))[0], parseVagueDate(r.get('TOp'))[0],
            parseVagueDate(r.get('TDate'))[0], r.get('TF'), r.get('UNState'), r.get('Comment'),
        )


def orgRows(orgsRows):
    for r in orgsRows:
        yield (
            r['Code'], r.get('UCode'), r.get('StateCode'), r.get('Type'), r.get('Class'),
            r.get('TStart'), r.get('TStop'), r.get('ShortEName') or r.get('ShortName'),
            r.get('EName') or r.get('Name'), r.get('Parent'), r.get('Location'),
        )


def launchRows(launchlogRows):
    for r in launchlogRows:
        launchDate, uncertain = parseVagueDate(r.get('Launch_Date'))
        yield (
            r['Launch_Tag'], r.get('Piece'), r.get('JCAT'), launchDate, int(uncertain),
            r.get('Launch_Date'), r.get('Name'), r.get('SatOwner'), r.get('SatState'),
            r.get('LV_Type'), r.get('Flight_ID'), r.get('Launch_Site'), r.get('Launch_Pad'),
            r.get('Agency'), r.get('LVState'), r.get('Launch_Code'),
        )


# Each GCAT file and the table it fills: (file, table, column definitions,
# primary key, row builder). Column order matches the row builders above.
TABLES = [
    ('cat/satcat.tsv', 'gcatObjects', '''
        jcat TEXT PRIMARY KEY, noradID INTEGER, launchTag TEXT, piece TEXT,
        satType TEXT, coarseType TEXT, name TEXT, payloadName TEXT,
        launchDate TEXT, launchDateRaw TEXT, decayDate TEXT, decayDateUncertain INTEGER,
        status TEXT, owners TEXT, ownerCode TEXT, stateCode TEXT, manufacturer TEXT,
        bus TEXT, massKg REAL, perigeeKm REAL, apogeeKm REAL, inclinationDeg REAL,
        opOrbit TEXT, parent TEXT, lengthM REAL, diameterM REAL, spanM REAL, shape TEXT''', objectRows,
     ['CREATE INDEX IF NOT EXISTS gcatObjectsByNorad ON gcatObjects (noradID)',
      'CREATE INDEX IF NOT EXISTS gcatObjectsByLaunch ON gcatObjects (launchTag)']),
    # TLast/TOp/TDate are stored as GCAT gives them; their exact meanings
    # (last contact / end of operations / end of mission?) should be
    # confirmed against GCAT's documentation before "operational" counts
    # rely on them.
    ('cat/psatcat.tsv', 'gcatPayloads', '''
        jcat TEXT PRIMARY KEY, piece TEXT, name TEXT, program TEXT, payloadClass TEXT,
        category TEXT, result TEXT, control TEXT, discipline TEXT,
        tLast TEXT, tOp TEXT, tDate TEXT, tf TEXT, unState TEXT, comment TEXT''',
     payloadRows, []),
    ('tables/orgs.tsv', 'gcatOrgs', '''
        code TEXT PRIMARY KEY, uCode TEXT, stateCode TEXT, orgType TEXT, orgClass TEXT,
        tStart TEXT, tStop TEXT, shortName TEXT, name TEXT, parent TEXT, location TEXT''',
     orgRows, []),
    ('derived/launchlog.tsv', 'gcatLaunches', '''
        launchTag TEXT NOT NULL, piece TEXT, jcat TEXT, launchDate TEXT,
        launchDateUncertain INTEGER, launchDateRaw TEXT, payloadName TEXT, satOwner TEXT,
        satState TEXT, launchVehicle TEXT, flightID TEXT, launchSite TEXT, launchPad TEXT,
        agency TEXT, lvState TEXT, launchCode TEXT''',
     launchRows,
     ['CREATE INDEX IF NOT EXISTS gcatLaunchesByTag ON gcatLaunches (launchTag)']),
]


# Every object GCAT has a decay date for, summarised: one row per decay year,
# coarse type (P payload, R rocket stage, D debris, C component ...) and
# status (R re-entered, D de-orbited, L landed, E / DSO left Earth orbit,
# N never reached orbit ...). gcatObjects drops re-entered stages and debris
# to stay small, so this is where re-entries per year come from. Built from
# the same download as gcatObjects.
# spacex: 1 if SpaceX is among the object's owners (any of its GCAT codes,
# as orbitStats.SPACEX_ORG_CODES), for the LAUNCHES W/O SPACEX filter.
DECAY_TABLE = ('gcatDecays', """
    year INTEGER, coarseType TEXT, status TEXT, spacex INTEGER, objects INTEGER,
    PRIMARY KEY (year, coarseType, status, spacex)""")
SPACEX_ORG_CODES = {'SPX', 'SPXES', 'SPXS', 'SPXT', 'SPXTX'}


# Every object that is the parent of a piece of debris still in orbit (GCAT
# Parent -- the object it broke off), whether or not the parent itself is
# still up: gcatObjects drops re-entered stages, so the parent's name, type
# and dates are kept here for the DEBRIS group's origin chart.
PARENT_TABLE = ('gcatParents', """
    jcat TEXT PRIMARY KEY, name TEXT, coarseType TEXT, launchDate TEXT, decayDate TEXT, owners TEXT,
    stateCode TEXT""")


def parentRows(satcatRows):
    byJcat = {r['JCAT']: r for r in satcatRows}
    parents = {nullable(r.get('Parent')) for r in satcatRows
               if (r.get('Type') or '')[:1] == 'D' and r.get('Status') in IN_ORBIT_STATUSES}
    rows = []
    for jcat in sorted(p for p in parents if p and p in byJcat):
        r = byJcat[jcat]
        rows.append((jcat, r.get('Name'), (r.get('Type') or '')[:1] or None, parseVagueDate(r.get('LDate'))[0],
                     parseVagueDate(r.get('DDate'))[0], r.get('Owner'), r.get('State')))
    return rows


# Every catalogued piece of debris (coarse type D) ever, summarised by year:
# how many were created -- by break-up date (SDate, when the piece separated;
# its launch date if that's missing) -- and how many came back down (status R,
# D or L, by decay date), with and without SpaceX-owned pieces. gcatObjects
# drops re-entered debris, so this is where the debris history comes from.
DEBRIS_TABLE = ('gcatDebrisYears', """
    year INTEGER, spacex INTEGER, created INTEGER, reentered INTEGER,
    PRIMARY KEY (year, spacex)""")
DEBRIS_REENTRY_STATUSES = {'R', 'R?', 'D', 'L', 'L?'}


def debrisYearRows(satcatRows):
    counts = {}
    for r in satcatRows:
        if (r.get('Type') or '')[:1] != 'D':
            continue
        spacex = int(bool(SPACEX_ORG_CODES.intersection((r.get('Owner') or '').split('/'))))
        created = parseVagueDate(r.get('SDate'))[0] or parseVagueDate(r.get('LDate'))[0]
        if created:
            key = (int(created[:4]), spacex)
            counts.setdefault(key, [0, 0])[0] += 1
        decayed = parseVagueDate(r.get('DDate'))[0]
        if decayed and r.get('Status') in DEBRIS_REENTRY_STATUSES:
            key = (int(decayed[:4]), spacex)
            counts.setdefault(key, [0, 0])[1] += 1
    return [(year, spacex, c, d) for (year, spacex), (c, d) in sorted(counts.items())]


def decayRows(satcatRows):
    counts = {}
    for r in satcatRows:
        decayDate, _ = parseVagueDate(r.get('DDate'))
        if not decayDate:
            continue
        spacex = int(bool(SPACEX_ORG_CODES.intersection((r.get('Owner') or '').split('/'))))
        key = (int(decayDate[:4]), (r.get('Type') or '')[:1] or None, r.get('Status'), spacex)
        counts[key] = counts.get(key, 0) + 1
    return [(*key, n) for key, n in sorted(
        counts.items(), key=lambda kv: (kv[0][0], kv[0][1] or '', kv[0][2] or '', kv[0][3]))]


# --- Database ---------------------------------------------------------------

def ensureSchema(db):
    for _, table, columns, _, indexes in TABLES:
        db.execute(f'CREATE TABLE IF NOT EXISTS {table} ({columns})')
        for statement in indexes:
            db.execute(statement)
    # An older gcatDecays without the spacex column is dropped, so it's
    # rebuilt (empty -> the satellite catalogue is reloaded this run).
    decayColumns = [row[1] for row in db.execute(f'PRAGMA table_info({DECAY_TABLE[0]})')]
    if decayColumns and 'spacex' not in decayColumns:
        db.execute(f'DROP TABLE {DECAY_TABLE[0]}')
    db.execute(f'CREATE TABLE IF NOT EXISTS {DECAY_TABLE[0]} ({DECAY_TABLE[1]})')
    db.execute(f'CREATE TABLE IF NOT EXISTS {PARENT_TABLE[0]} ({PARENT_TABLE[1]})')
    db.execute(f'CREATE TABLE IF NOT EXISTS {DEBRIS_TABLE[0]} ({DEBRIS_TABLE[1]})')
    # gcatObjects from before the parent column: add it (empty until the next
    # satellite-catalogue load, which the empty gcatParents forces).
    objectColumns = [row[1] for row in db.execute('PRAGMA table_info(gcatObjects)')]
    if objectColumns and 'parent' not in objectColumns:
        db.execute('ALTER TABLE gcatObjects ADD COLUMN parent TEXT')
    # ... and from before the size columns (filled by the next forced load).
    for column, kind in (('lengthM', 'REAL'), ('diameterM', 'REAL'), ('spanM', 'REAL'), ('shape', 'TEXT')):
        if objectColumns and column not in objectColumns:
            db.execute(f'ALTER TABLE gcatObjects ADD COLUMN {column} {kind}')
    db.execute('''
        CREATE TABLE IF NOT EXISTS gcatFiles (
            path         TEXT PRIMARY KEY,
            lastModified TEXT,
            fetchedAt    TEXT,
            bytes        INTEGER,
            rows         INTEGER
        )
    ''')
    db.commit()


def replaceTable(db, table, rows):
    """Swaps in a whole new set of rows atomically: readers see either the
    old table or the new one, never a half-loaded one. Returns the count."""
    rows = list(rows)
    if not rows:
        raise ValueError(f'{table}: no rows parsed -- refusing to empty the table')
    placeholders = ','.join('?' * len(rows[0]))
    with db:  # one transaction: commit on success, roll back on error
        db.execute(f'DELETE FROM {table}')
        db.executemany(f'INSERT INTO {table} VALUES ({placeholders})', rows)
    return len(rows)


# --- Download -----------------------------------------------------------------

def fetchIfModified(db, path, force=False):
    """(text, Last-Modified header), or (None, None) when GCAT reports the
    file unchanged since our last fetch (HTTP 304). force skips the check."""
    request = urllib.request.Request(GCAT_BASE_URL + path, headers={'User-Agent': USER_AGENT})
    known = db.execute('SELECT lastModified FROM gcatFiles WHERE path = ?', (path,)).fetchone()
    if known and known[0] and not force:
        request.add_header('If-Modified-Since', known[0])
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SEC) as response:
            body = response.read()
            return body.decode('utf-8', errors='replace'), response.headers.get('Last-Modified')
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return None, None
        raise


def runGcatIngestion(db):
    """Returns the number of objects new to gcatObjects this run."""
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Starting GCAT Ingestion ===')
    ensureSchema(db)
    objectsBefore = {jcat for (jcat,) in db.execute('SELECT jcat FROM gcatObjects')}
    newObjects = 0
    failures = []
    handled = 0   # files loaded, or confirmed unchanged

    # A table derived from a file but still empty (e.g. gcatDecays, the first
    # run after it was added) means that file must be loaded even if unchanged.
    decaysMissing = any(not db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
                        for table in (DECAY_TABLE[0], PARENT_TABLE[0], DEBRIS_TABLE[0]))
    # Likewise a column added to gcatObjects that no row has filled yet (the
    # size columns, the first run after they were added).
    decaysMissing = decaysMissing or not db.execute(
        'SELECT 1 FROM gcatObjects WHERE lengthM IS NOT NULL OR spanM IS NOT NULL LIMIT 1').fetchone()

    for path, table, _, buildRows, _ in TABLES:
        try:
            text, lastModified = fetchIfModified(db, path, force=(table == 'gcatObjects' and decaysMissing))
        except (urllib.error.URLError, socket.timeout) as error:
            # One unreachable file shouldn't stop the others.
            print(f'  [{path}] ERROR {error}')
            failures.append(path)
            continue
        handled += 1
        if text is None:
            print(f'  [{path}] unchanged since last fetch -- skipped')
            continue
        parsed = parseTsv(text)
        count = replaceTable(db, table, buildRows(parsed))
        if table == 'gcatObjects':
            decays = decayRows(parsed)
            if decays:
                replaceTable(db, DECAY_TABLE[0], decays)
            print(f'  [{path}] {len(decays)} decay-summary rows -> {DECAY_TABLE[0]}')
            parents = parentRows(parsed)
            if parents:
                replaceTable(db, PARENT_TABLE[0], parents)
            print(f'  [{path}] {len(parents)} debris parents -> {PARENT_TABLE[0]}')
            debrisYears = debrisYearRows(parsed)
            if debrisYears:
                replaceTable(db, DEBRIS_TABLE[0], debrisYears)
            print(f'  [{path}] {len(debrisYears)} debris-history rows -> {DEBRIS_TABLE[0]}')
        db.execute(
            'INSERT OR REPLACE INTO gcatFiles (path, lastModified, fetchedAt, bytes, rows) '
            "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), ?, ?)",
            (path, lastModified, len(text.encode('utf-8')), count))
        db.commit()
        print(f'  [{path}] {count} rows -> {table}')
        if table == 'gcatObjects':
            newObjects = sum(1 for (jcat,) in db.execute('SELECT jcat FROM gcatObjects')
                             if jcat not in objectsBefore)

    if failures and handled == 0:
        # Every file failed -- recorded by trackRun() as a failed run.
        raise RuntimeError(f'GCAT unreachable: all {len(failures)} downloads failed')
    print(f'=== GCAT INGESTION COMPLETE ({newObjects} new objects'
          f'{", " + str(len(failures)) + " file(s) failed" if failures else ""}) ===\n')
    return newObjects


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    db = sqlite3.connect(DB_PATH)
    with trackRun(db, 'gcat') as run:
        run.changes = runGcatIngestion(db)
    db.commit()
    db.execute('VACUUM')
    db.close()
    # GRD VIEW's satellite brightness estimates come from GCAT's object
    # list and sizes, so they are rebuilt after every run too.
    from estimateBrightness import refreshBrightness
    brightnessDb = sqlite3.connect(DB_PATH, uri=True)
    refreshBrightness(brightnessDb)
    brightnessDb.close()
    # The ON-ORBIT overview's figures draw on GCAT, so refresh them after
    # every run -- even when GCAT's files were unchanged, as that's cheap and
    # keeps them right after a change to a chart's rules.
    from orbitStats import refreshAll
    refreshAll()
