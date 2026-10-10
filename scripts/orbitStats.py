"""Precomputed figures for the ON-ORBIT overview's charts and tables, stored
in ingestionDBs/onOrbitStats.db (a derived database: rebuilt by this
script, never committed).

Population: the NORAD catalogue (orbitalObjects.db -- CelesTrak and
Space-Track, refreshed by the orbital pipeline every 12 h): every object
that has not decayed -- payloads (objectType PAY), rocket bodies, debris and
unknown or untyped objects -- with its CURRENT perigee/apogee.
GCAT (gcat.db, scripts/ingestGcat.py, weekly) is joined in by NORAD number
only for ownership (state, owner organisations) and its payload category.
GCAT's own perigee/apogee are the orbit a satellite was first placed in
(e.g. Starlinks at ~280 km before raising to ~470 km), so they are never
used.

Filters; every figure is stored for every combination, so the page can
switch between them without recomputing:
  status: 'active'     -- in CelesTrak's 'active' group (operational status)
          'all'        -- regardless of status
  kind:   'satellites' -- all spacecraft minus crewed stations and their
                          visiting vehicles, and passive objects
          'spacecraft' -- every payload
          'objects'    -- every catalogued object: payloads, rocket bodies,
                          debris and unknown objects
  spacex: 'with'       -- SpaceX's payloads included        (charts only: the
          'without'    -- SpaceX's payloads left out         regime table shows both)
A station or visiting vehicle is GCAT category SS (ISS / Tiangong modules,
Progress, Shenzhou, Tianzhou, Cygnus ...), or -- for visitors GCAT hasn't
matched yet (e.g. a just-launched Crew Dragon) -- a member of CelesTrak's
'stations' group with no GCAT entry. (That group also lists small
satellites just released from the ISS; those are in GCAT as ordinary
payloads, so they stay satellites.) Passive: GCAT categories CAL
(calibration spheres) and TARG (ASAT targets).

Run after either source changes -- at the end of scripts/ingestGcat.py and
as the last step of scripts/runPipeline.sh -- and by hand after changing a
figure's rules, without re-downloading anything:

    python scripts/orbitStats.py
"""

import os
import sqlite3
from datetime import datetime, timezone

# The DBs live in the repo root's ingestionDBs/; this script sits in scripts/, one level down.
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ingestionDBs')
STATS_DB = os.path.join(DB_DIR, 'onOrbitStats.db')
GCAT_DB = os.path.join(DB_DIR, 'gcat.db')
ORBITAL_DB = os.path.join(DB_DIR, 'orbitalObjects.db')

STATUS_FILTERS = ['active', 'all']
KIND_FILTERS = ['satellites', 'spacecraft', 'objects']
SPACEX_FILTERS = ['with', 'without']
STATION_CATEGORY_PREFIX = 'SS'
PASSIVE_CATEGORIES = {'CAL', 'TARG'}
# Every GCAT organisation code for SpaceX (Hawthorne, El Segundo, Seattle --
# Starlink's owner -- McGregor, and its passenger code).
SPACEX_ORG_CODES = {'SPX', 'SPXES', 'SPXS', 'SPXT', 'SPXTX'}

POPULATION_SQL = '''
    SELECT o.noradID, o.name, o.objectType, o.perigee, o.apogee, o.inclination,
           g.jcat, g.stateCode, g.owners, p.category, p.payloadClass,
           o.noradID IN (SELECT noradID FROM orb.orbital_object_groups WHERE groupName = 'active')   AS inActive,
           o.noradID IN (SELECT noradID FROM orb.orbital_object_groups WHERE groupName = 'stations') AS inStations,
           o.noradID IN (SELECT noradID FROM orb.orbital_object_groups WHERE groupName = 'starlink') AS inStarlink
    FROM orb.orbital_objects o
    LEFT JOIN gcat.gcatObjects g ON g.noradID = o.noradID
    LEFT JOIN gcat.gcatPayloads p ON p.jcat = g.jcat
    WHERE o.decayDate IS NULL
'''


def openSources(statsPath=STATS_DB, gcatPath=GCAT_DB, orbitalPath=ORBITAL_DB):
    """The stats DB, with both sources attached read-only as 'gcat' and 'orb'."""
    # uri=True on the main connection is what lets ATTACH accept the
    # read-only 'file:...?mode=ro' URIs below.
    db = sqlite3.connect(f'file:{statsPath}', uri=True)
    db.execute('ATTACH DATABASE ? AS gcat', (f'file:{gcatPath}?mode=ro',))
    db.execute('ATTACH DATABASE ? AS orb', (f'file:{orbitalPath}?mode=ro',))
    return db


def replaceRows(db, table, columns, rows):
    with db:
        # Dropped and recreated, not just emptied, so a change to a table's
        # columns takes effect -- the stats DB is entirely derived.
        db.execute(f'DROP TABLE IF EXISTS {table}')
        db.execute(f'CREATE TABLE {table} ({columns})')
        if rows:
            db.executemany(f'INSERT INTO {table} VALUES ({",".join("?" * len(rows[0]))})', rows)
        db.execute('CREATE TABLE IF NOT EXISTS statsUpdated (statTable TEXT PRIMARY KEY, updatedAt TEXT)')
        db.execute('INSERT OR REPLACE INTO statsUpdated VALUES (?, ?)',
                   (table, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))


# --- Population -----------------------------------------------------------------

def loadPopulation(db):
    """One dict per in-orbit object in the NORAD catalogue, with its filter
    flags and ownership worked out. Only payloads can be satellites or
    stations; for a rocket body or debris, GCAT's owner and state are those
    GCAT records for that object."""
    orgClasses = dict(db.execute('SELECT code, orgClass FROM gcat.gcatOrgs'))
    population = []
    for (norad, name, objectType, perigee, apogee, inclination, jcat, state, owners, category, payloadClass,
         inActive, inStations, inStarlink) in db.execute(POPULATION_SQL):
        payload = objectType == 'PAY'
        categories = set((category or '').replace('?', '').replace('*', '').split('/'))
        station = (category or '').startswith(STATION_CATEGORY_PREFIX) or (jcat is None and bool(inStations))
        passive = bool(categories & PASSIVE_CATEGORIES)
        starlink = bool(inStarlink) or (name or '').upper().startswith('STARLINK')
        spacex = bool(SPACEX_ORG_CODES.intersection((owners or '').split('/'))) or (jcat is None and starlink)
        population.append({
            'perigee': perigee, 'apogee': apogee, 'inclination': inclination, 'state': state,
            'active': bool(inActive), 'payload': payload,
            'satellite': payload and not station and not passive,
            'starlink': starlink, 'spacex': spacex,
            'sector': payloadSector(jcat, payloadClass, owners, orgClasses),
            # First-listed GCAT owner code; None if not in GCAT. A multi-owner
            # payload counts once, under its first owner.
            'owner': (owners or '').split('/')[0] or None if jcat is not None else None,
        })
    return population


# GCAT's sector classes. A payload's own class first; when it has none, its
# (first) owner organisation's -- GCAT: a payload's class is "usually the
# same as the class of the owner organization, but not always". A few
# payloads are dual-class (e.g. CB, TerraSAR-X; BD, GeoEye-1): counted under
# the first letter. None: no GCAT match, or no class anywhere.
SECTORS = ['A', 'B', 'C', 'D', None]


def payloadSector(jcat, payloadClass, owners, orgClasses):
    if jcat is None:
        return None
    for candidate in (payloadClass, orgClasses.get((owners or '').split('/')[0])):
        letter = (candidate or '').strip()[:1].upper()
        if letter in ('A', 'B', 'C', 'D'):
            return letter
    return None


def matchesFilters(item, status, kind):
    if status == 'active' and not item['active']:
        return False
    if kind == 'satellites':
        return item['satellite']
    if kind == 'spacecraft':
        return item['payload']
    return True   # 'objects


def filteredSets(population):
    """(status, kind, items) for every status/kind combination."""
    for status in STATUS_FILTERS:
        for kind in KIND_FILTERS:
            yield status, kind, [item for item in population if matchesFilters(item, status, kind)]


def chartFilteredSets(population):
    """(status, kind, spacex, items) for every combination of all three
    filters -- the charts. (The regime table shows with and without SpaceX
    side by side, so uses filteredSets.)"""
    for status, kind, items in filteredSets(population):
        for spacex in SPACEX_FILTERS:
            yield status, kind, spacex, (items if spacex == 'with' else [i for i in items if not i['spacex']])


# --- By nationality ------------------------------------------------------------

NATIONALITY_TOP_STATES = 12              # largest states by payload count, shown individually...
NATIONALITY_ALWAYS_SHOWN = ['I-ESA']     # ...plus these, wherever they rank
# GCAT's ShortEName is used for each state's label, except where it's an
# abbreviation (its full EName is often a formal style -- "Japan (Nippon),
# State of" -- so neither works on its own for those).
NATIONALITY_DISPLAY_NAMES = {
    'US': 'United States',
    'UK': 'United Kingdom',
    'SU': 'Soviet Union',
    'I-ESA': 'European Space Agency',
}


def nationalityRows(db, items):
    """Rows for one filter combination: the US split into Starlink and the
    rest, the largest NATIONALITY_TOP_STATES states and NATIONALITY_ALWAYS_SHOWN
    individually, everything else -- including payloads with no GCAT match,
    hence no state -- as one 'Other' row, in display order."""
    counts = {}
    for item in items:
        counts[item['state']] = counts.get(item['state'], 0) + 1
    byState = sorted(((code, n) for code, n in counts.items() if code), key=lambda kv: -kv[1])
    starlink = sum(1 for item in items if item['state'] == 'US' and item['starlink'])

    def label(code):
        if code in NATIONALITY_DISPLAY_NAMES:
            return NATIONALITY_DISPLAY_NAMES[code]
        found = db.execute('SELECT shortName, name FROM gcat.gcatOrgs WHERE code = ?', (code,)).fetchone()
        return (found[0] or found[1]) if found else code

    shownCodes = [code for code, _ in byState[:NATIONALITY_TOP_STATES]]
    shownCodes += [code for code in NATIONALITY_ALWAYS_SHOWN if code not in shownCodes and code in counts]
    rows = []
    for code in shownCodes:
        if code == 'US':
            rows.append(('United States – Starlink', 'US', starlink))
            rows.append(('United States – Other', 'US', counts['US'] - starlink))
        else:
            rows.append((label(code), code, counts[code]))
    # No empty bars -- e.g. the Starlink row once SpaceX is left out.
    rows = [row for row in rows if row[2]]
    otherStates = [code for code, _ in byState if code not in shownCodes]
    otherCount = sum(counts[code] for code in otherStates) + counts.get(None, 0)
    if otherCount:
        rows.append((f'Other ({len(otherStates)} countries & organisations)', None, otherCount))
    return rows


def storeNationality(db, population=None):
    population = population if population is not None else loadPopulation(db)
    rows = []
    for status, kind, spacex, items in chartFilteredSets(population):
        rows += [(status, kind, spacex, rank, *row)
                 for rank, row in enumerate(nationalityRows(db, items), start=1)]
    replaceRows(db, 'onOrbitNationality',
                'statusFilter TEXT, kindFilter TEXT, spacexFilter TEXT, rank INTEGER, label TEXT, stateCode TEXT, '
                'payloads INTEGER, PRIMARY KEY (statusFilter, kindFilter, spacexFilter, rank)', rows)
    return rows


# --- By current orbit regime -------------------------------------------------
# Shape first, then altitude, both from the CURRENT orbit:
#   HEO    highly elliptical -- eccentricity above 0.25, whatever the
#          altitude (Molniya, Tundra, transfer orbits, many science orbits).
#          Eccentricity is worked out from the same perigee/apogee as the
#          altitude, so every classified object has one.
# then, for near-circular orbits, by mean altitude (perigee + apogee) / 2:
#   VLEO   below 450 km -- the most common definition, used by ESA and
#          DARPA (others put the ceiling at 400 or 500 km)
#   LEO    450 to 2,000 km
#   MEO    2,000 to 35,586 km
#   GEO    within +/-200 km of 35,786 km
#   > GEO  above that -- mostly retired GEO satellites in graveyard orbits
# (LEO/MEO/GEO cut-offs as server.py's ALTITUDE_REGIME_SQL, the ADD OBJ search.)
REGIMES = ['VLEO', 'LEO', 'MEO', 'GEO', '> GEO', 'HEO']
VLEO_CEILING_KM = 450
HEO_MIN_ECCENTRICITY = 0.25
EARTH_EQUATORIAL_RADIUS_KM = 6378.137


def eccentricity(perigeeKm, apogeeKm):
    """From perigee and apogee altitudes: (ra - rp) / (ra + rp), radii
    measured from Earth's centre."""
    perigeeRadius = perigeeKm + EARTH_EQUATORIAL_RADIUS_KM
    apogeeRadius = apogeeKm + EARTH_EQUATORIAL_RADIUS_KM
    return (apogeeRadius - perigeeRadius) / (apogeeRadius + perigeeRadius)


def orbitRegime(perigeeKm, apogeeKm):
    if eccentricity(perigeeKm, apogeeKm) > HEO_MIN_ECCENTRICITY:
        return 'HEO'
    meanAltitude = (perigeeKm + apogeeKm) / 2
    if meanAltitude < VLEO_CEILING_KM:
        return 'VLEO'
    if meanAltitude < 2000:
        return 'LEO'
    if meanAltitude < 35586:
        return 'MEO'
    if meanAltitude <= 35986:
        return 'GEO'
    return '> GEO'


def regimeCounts(items):
    """{regime: [all, excluding SpaceX]}; payloads with no current
    perigee/apogee are 'unclassified'."""
    counts = {regime: [0, 0] for regime in REGIMES + ['unclassified']}
    for item in items:
        if item['perigee'] is None or item['apogee'] is None:
            regime = 'unclassified'
        else:
            regime = orbitRegime(item['perigee'], item['apogee'])
        counts[regime][0] += 1
        if not item['spacex']:
            counts[regime][1] += 1
    return counts


def storeRegimes(db, population=None):
    population = population if population is not None else loadPopulation(db)
    rows = []
    for status, kind, items in filteredSets(population):
        counts = regimeCounts(items)
        rows += [(status, kind, regime, order, *counts[regime])
                 for order, regime in enumerate(REGIMES + ['unclassified'], start=1)]
    replaceRows(db, 'onOrbitRegimes',
                'statusFilter TEXT, kindFilter TEXT, regime TEXT, sortOrder INTEGER, allPayloads INTEGER, '
                'exclSpacex INTEGER, PRIMARY KEY (statusFilter, kindFilter, regime)', rows)
    return rows


# --- By inclination -------------------------------------------------------------
# Histogram of CURRENT inclination in 5-degree buckets across the full
# 0-180 degree range -- every bucket stored, empty ones too, so the chart's
# axis is the same whatever the filters. A bucket holds its lower edge but
# not its upper (50 deg is in 50-55); 180 itself goes in the last bucket.
# Payloads with no inclination on file are stored with bucketStart NULL.
INCLINATION_BUCKET_DEG = 5
INCLINATION_MAX_DEG = 180


def inclinationBucket(inclinationDeg):
    """Lower edge of the bucket an inclination falls in, or None if unknown."""
    if inclinationDeg is None:
        return None
    lastBucket = INCLINATION_MAX_DEG - INCLINATION_BUCKET_DEG
    return min(int(inclinationDeg // INCLINATION_BUCKET_DEG) * INCLINATION_BUCKET_DEG, lastBucket)


def storeInclination(db, population=None):
    population = population if population is not None else loadPopulation(db)
    rows = []
    for status, kind, spacex, items in chartFilteredSets(population):
        counts = {start: 0 for start in range(0, INCLINATION_MAX_DEG, INCLINATION_BUCKET_DEG)}
        counts[None] = 0
        for item in items:
            counts[inclinationBucket(item['inclination'])] += 1
        rows += [(status, kind, spacex, start, start + INCLINATION_BUCKET_DEG if start is not None else None, n)
                 for start, n in counts.items()]
    replaceRows(db, 'onOrbitInclination',
                'statusFilter TEXT, kindFilter TEXT, spacexFilter TEXT, bucketStart INTEGER, bucketEnd INTEGER, '
                'payloads INTEGER', rows)
    return rows


# --- By sector -------------------------------------------------------------------

def storeSector(db, population=None):
    """Payloads per GCAT sector (SECTORS, None last as 'unknown'), for every
    chart filter combination."""
    population = population if population is not None else loadPopulation(db)
    rows = []
    for status, kind, spacex, items in chartFilteredSets(population):
        counts = {sector: 0 for sector in SECTORS}
        for item in items:
            counts[item['sector']] += 1
        rows += [(status, kind, spacex, sector or 'unknown', order, counts[sector])
                 for order, sector in enumerate(SECTORS, start=1)]
    replaceRows(db, 'onOrbitSector',
                'statusFilter TEXT, kindFilter TEXT, spacexFilter TEXT, sector TEXT, sortOrder INTEGER, '
                'payloads INTEGER, PRIMARY KEY (statusFilter, kindFilter, spacexFilter, sector)', rows)
    return rows


# --- By owner --------------------------------------------------------------------
# Every owner (first-listed GCAT owner code, as GCAT records it -- a legal
# entity, not a parent group: e.g. OneWeb appears as two codes), ranked by
# payload count, for every chart filter combination. The page shows as many
# as fit its width; the rest still count towards the totals. Payloads with
# no owner (not yet in GCAT) are stored as one row with rank 0.

def storeOwners(db, population=None):
    population = population if population is not None else loadPopulation(db)
    names = {code: (short or name or code, name or short or code, state)
             for code, short, name, state in db.execute('SELECT code, shortName, name, stateCode FROM gcat.gcatOrgs')}
    rows = []
    for status, kind, spacex, items in chartFilteredSets(population):
        counts = {}
        for item in items:
            counts[item['owner']] = counts.get(item['owner'], 0) + 1
        noOwner = counts.pop(None, 0)
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        for rank, (code, n) in enumerate(ranked, start=1):
            label, fullName, state = names.get(code.rstrip('?'), (code, code, None))
            rows.append((status, kind, spacex, rank, code, label, fullName, state, n))
        rows.append((status, kind, spacex, 0, None, 'No owner on file', None, None, noOwner))
    replaceRows(db, 'onOrbitOwners',
                'statusFilter TEXT, kindFilter TEXT, spacexFilter TEXT, rank INTEGER, ownerCode TEXT, '
                'label TEXT, fullName TEXT, stateCode TEXT, payloads INTEGER, '
                'PRIMARY KEY (statusFilter, kindFilter, spacexFilter, rank)', rows)
    return rows


# --- Launch history (LAUNCHES section) ------------------------------------------
# From GCAT alone. Payloads launched each year since 1957 (the current year:
# to date), by GCAT sector (Starlink within commercial), counted by launch
# date. Payloads that never reached orbit (GCAT status N,
# launch failures) are left out, so this is new payloads in orbit per year. Re-entries per year come
# from gcatDecays (scripts/ingestGcat.py): objects that came back down --
# status R re-entered, D de-orbited, L landed (and their uncertain R? / L?) --
# by coarse type. Attached / docked objects (AR, DK ...) come down with what
# they are attached to and aren't counted again; departures to deep space
# (E, DSO ...) aren't re-entries.
PAYLOAD_SERIES = [('A', 'Academic & amateur'), ('B', 'Commercial'), ('C', 'Civil government'),
                  ('D', 'Defence'), ('unknown', 'Unknown sector')]
REENTRY_STATUSES = {'R', 'R?', 'D', 'L', 'L?'}
REENTRY_KINDS = [('P', 'Payloads'), ('R', 'Rocket bodies'), ('D', 'Debris'), ('other', 'Other')]


def payloadsLaunchedByYear(db, today=None):
    today = today or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    orgClasses = dict(db.execute('SELECT code, orgClass FROM gcat.gcatOrgs'))
    payloads = []
    for jcat, name, launchDate, decayDate, status, owners, payloadClass in db.execute(
            "SELECT g.jcat, g.name, g.launchDate, g.decayDate, g.status, g.owners, p.payloadClass "
            "FROM gcat.gcatObjects g LEFT JOIN gcat.gcatPayloads p ON p.jcat = g.jcat "
            "WHERE g.coarseType = 'P' AND g.launchDate IS NOT NULL AND COALESCE(g.status, '') <> 'N'"):
        sector = payloadSector(jcat, payloadClass, owners, orgClasses)
        spacex = bool(SPACEX_ORG_CODES.intersection((owners or '').split('/')))
        payloads.append((int(launchDate[:4]), sector or 'unknown', spacex))
    counts = {}
    for year, series, spacex in payloads:
        for spacexFilter in SPACEX_FILTERS:
            if spacexFilter == 'without' and spacex:
                continue
            counts[(spacexFilter, year, series)] = counts.get((spacexFilter, year, series), 0) + 1
    rows = []
    for spacexFilter in SPACEX_FILTERS:
        for year in range(1957, int(today[:4]) + 1):
            rows += [(spacexFilter, year, key, order, counts.get((spacexFilter, year, key), 0))
                     for order, (key, _) in enumerate(PAYLOAD_SERIES, start=1)]
    return rows


def reentriesByYear(db):
    try:
        found = db.execute('SELECT year, coarseType, status, spacex, objects FROM gcat.gcatDecays').fetchall()
    except sqlite3.OperationalError:
        return []   # GCAT not yet re-ingested with the decay summary
    counts = {}
    for year, coarseType, status, spacex, n in found:
        if status not in REENTRY_STATUSES:
            continue
        kind = coarseType if coarseType in ('P', 'R', 'D') else 'other'
        for spacexFilter in SPACEX_FILTERS:
            if spacexFilter == 'without' and spacex:
                continue
            counts[(spacexFilter, year, kind)] = counts.get((spacexFilter, year, kind), 0) + n
    years = sorted({year for _, year, _ in counts})
    return [(spacexFilter, year, kind, order, counts.get((spacexFilter, year, kind), 0))
            for spacexFilter in SPACEX_FILTERS
            for year in years for order, (kind, _) in enumerate(REENTRY_KINDS, start=1)]


def storeLaunchHistory(db, population=None):
    rows = payloadsLaunchedByYear(db)
    db.execute('DROP TABLE IF EXISTS launchPayloadsInOrbit')   # replaced by launchPayloadsLaunched
    replaceRows(db, 'launchPayloadsLaunched',
                'spacexFilter TEXT, year INTEGER, series TEXT, sortOrder INTEGER, payloads INTEGER, '
                'PRIMARY KEY (spacexFilter, year, series)', rows)
    reentries = reentriesByYear(db)
    replaceRows(db, 'launchReentries',
                'spacexFilter TEXT, year INTEGER, kind TEXT, sortOrder INTEGER, objects INTEGER, '
                'PRIMARY KEY (spacexFilter, year, kind)', reentries)
    return rows, reentries


ALL_STATS = [storeNationality, storeRegimes, storeInclination, storeSector, storeOwners, storeLaunchHistory]


def refreshAll():
    """Recomputes every ON-ORBIT figure. Skipped (returns False) until both
    source databases exist -- e.g. before GCAT's first run on a new server."""
    missing = [path for path in (GCAT_DB, ORBITAL_DB) if not os.path.exists(path)]
    if missing:
        print(f'  [orbitStats] skipped -- missing {", ".join(os.path.basename(p) for p in missing)}')
        return False
    db = openSources()
    try:
        population = loadPopulation(db)
        for stat in ALL_STATS:
            stat(db, population)
        print(f'  [orbitStats] {len(ALL_STATS)} tables refreshed in {os.path.basename(STATS_DB)} '
              f'({len(population)} objects in orbit, {sum(1 for i in population if i["payload"])} payloads)')
    finally:
        db.close()
    return True


if __name__ == '__main__':
    refreshAll()
