"""Publish step: builds the databases the website reads (site<Type>.db)
from the ingestion databases, and swaps each one into place whole.

Step 9 of 0_documentation/plans/dbRefactorPlan.md.

    python scripts/publishSite.py orbital|news|sky|groundSegment|weather|all
        [--no-celestrak]  build groups as if CelesTrak were unavailable
                          (our own rules only -- what the live server
                          gets while CelesTrak blocks it)
        [--force]         publish even if the sanity check objects

ONE PUBLISH, for each type:
  1. Read its ingestion databases, read-only.
  2. Build site<Type>.db.tmp beside the live file -- always from
     scratch, never patched (see the plan: small files, totals that
     depend on every object, and a rebuild can't carry a mistake over).
  3. Check it: PRAGMA integrity_check, and a sanity check that refuses
     to publish when a key table has shrunk by more than MAX_DROP against
     the file being replaced.
  4. Copy the live file to site<Type>.db.prev, then os.replace the .tmp
     into place -- atomic, so the website only ever sees a whole file.
If any of that fails, the live file is untouched.

ORBITAL (siteOrbital.db) is the only type with real work:
  - objects: Space-Track's catalogue (ingestionSpaceTrack.db) -- every
    object in its latest full pass or updated since, with an element set
    no older than MAX_ELEMENT_AGE_DAYS, plus objects that decayed within
    RECENT_DECAY_DAYS (kept with their decay date). Elements come from
    Space-Track only: CelesTrak supplies none (decision A) and SatNOGS
    none (step 7). Column names and codes are the ones the website has
    always read (PAY / R/B / DEB / UNK, epoch ending 'Z', ...).
  - groups: groupRules.groupMembers -- CelesTrak's lists while they are
    available, our own rules otherwise (decision A, extended). Each
    rule's agreement with CelesTrak is printed.
  - radio: SatNOGS transmitters, linked to a NORAD object by
    norad_follow_id, then the designator from SatNOGS's TLE, then their
    own number; then rfSelection.choose_rf picks the main downlink and
    uplink.
  - derived: EIRP and receive G/T (enrichEirp; its class tier falls back
    to GCAT -- enrichEirp.gcat_class -- while CelesTrak is unavailable), brightness
    (estimateBrightness -> gcatBrightness), the ON-ORBIT / LAUNCHES stats
    (orbitStats).
  - GCAT: only the tables and columns the website reads.
  - ingestionRuns: every source database's run history, for the
    landing page's freshness table.
The objects are first built in a separate staging file, because the
stats and brightness code attach the orbital table as a database of its
own; its tables are then copied into the site file.

NEWS, SKY, GROUND SEGMENT: copies of the tables the website reads.

WEATHER (siteWeather.db; plan: 0_documentation/plans/spaceWeatherIngestionPlan.md,
section 6), from ingestionSWPC.db (required) and ingestionGFZ.db,
ingestionDONKI.db, ingestionGCR.db, ingestionSILSO.db and ingestionTEC.db (used if present):
  - samples: every series in full, except the high-rate ones (L1, GOES
    X-ray, GOES protons, 1-minute Kp), which keep only the last
    WEATHER_NATIVE_DAYS days at native resolution;
  - samplesHourly: hourly means of the high-rate series for the last
    WEATHER_HOURLY_DAYS days (they are 90 days in the ingestion database
    anyway);
  - events: DONKI and SWPC events; latestMaps: the newest map of each kind;
  - derived series in samples: derivedF107A81 (trailing 81-day mean of
    GFZ's adjusted F10.7) and derivedStormG (G-scale of each day's highest
    GFZ Kp);
  - ingestionRuns of the sources, for the freshness table.
  The neutron-monitor (gcr) and SILSO (silso) series are copied whole: hourly
  cosmic-ray data are small, the monthly records are kept for good.
  - tecMaps (ingestionTEC.db): every held CODE and GloTEC total-electron-content map
    (7 days; each a gzipped compact JSON map the server hands out as it is); the TEC
    summary series come across with the other samples.

EST. SIZE (rcsSize) is CelesTrak's radar cross-section in m^2, kept for
good once known (ingestionCelesTrak.db satcatRcs; decided 2026-10-21:
satellites don't change size). Space-Track's SMALL / MEDIUM / LARGE is
published alongside as rcsCategory.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import dbPaths
import enrichEirp
import estimateBrightness
import groupRules
import orbitStats
import weatherDerived
from dbPaths import (CELESTRAK_DB, GCAT_DB, GROUND_SEGMENT_DB, NEWS_DB, SATNOGS_DB, SITE_GROUND_SEGMENT_DB,
                     SITE_NEWS_DB, SITE_ORBITAL_DB, SITE_SKY_DB, SITE_WEATHER_DB, SKY_DB, SPACETRACK_DB, SWPC_DB, GFZ_DB,
                     DONKI_DB, GCR_DB, SILSO_DB, TEC_DB, dbPath)
from rfSelection import choose_rf

MAX_ELEMENT_AGE_DAYS = 30
RECENT_DECAY_DAYS = 30
MAX_DROP = 0.10   # refuse to publish when a key table shrinks by more than this

OBJECT_TYPES = {'PAYLOAD': 'PAY', 'ROCKET BODY': 'R/B', 'DEBRIS': 'DEB', 'UNKNOWN': 'UNK'}

ORBITAL_TABLE_SQL = '''
    CREATE TABLE orbital_objects (
        noradID INTEGER PRIMARY KEY, name TEXT, objectID TEXT, epoch TEXT,
        meanMotion REAL, eccentricity REAL, inclination REAL, raOfAscNode REAL,
        argOfPericenter REAL, meanAnomaly REAL, bstar REAL, meanMotionDot REAL, meanMotionDdot REAL,
        objectType TEXT, owner TEXT, launchDate TEXT, launchSite TEXT, decayDate TEXT,
        rcsSize REAL, rcsCategory TEXT, period REAL, apogee REAL, perigee REAL,
        source TEXT, fetchedAt TEXT,
        downlinkBand TEXT, eirpDbw REAL, eirpSource TEXT,
        satRxGainDbi REAL, satNoiseTempK REAL, satGtDbk REAL, satGtSource TEXT,
        dlFreqHz REAL, ulFreqHz REAL, dlBandwidthHz REAL, rfMode TEXT, rfBaud REAL, rfSource TEXT
    )
'''
GROUPS_TABLE_SQL = '''
    CREATE TABLE orbital_object_groups (
        noradID INTEGER NOT NULL, groupName TEXT NOT NULL, PRIMARY KEY (noradID, groupName)
    )
'''

# GCAT columns the website reads from gcatObjects (server.py).
GCAT_OBJECT_COLUMNS = ('noradID', 'name', 'owners', 'ownerCode', 'stateCode', 'manufacturer', 'bus',
                       'massKg', 'lengthM', 'diameterM', 'spanM')

# Tables whose row count the sanity check compares, per type.
SANITY_TABLES = {
    'orbital': ('orbital_objects', 'onOrbitObjects', 'gcatLaunches'),
    'news': ('articles',),
    'sky': ('skyStars',),
    'groundSegment': ('ground_segment_assets',),
    'weather': ('samples',),
}

WEATHER_NATIVE_DAYS = 3
WEATHER_HOURLY_DAYS = 90
HIGH_RATE_PREFIXES = ('l1', 'goesXray', 'goesProton')   # series sampled every 1 to 5 minutes
HOURLY_MIN_READINGS = (('goesProton', 6), ('', 30))     # an hourly mean needs half an hour of data (6 of 12 5-minute readings)


class PublishRefused(Exception):
    pass


def utcNow():
    return datetime.now(timezone.utc)


def isoDay(dt):
    return dt.strftime('%Y-%m-%d')


def connectUri(path, readOnly=False):
    return sqlite3.connect(f'file:{path}' + ('?mode=ro' if readOnly else ''), uri=True)


def attach(db, path, schema):
    db.execute('ATTACH DATABASE ? AS ' + schema, (f'file:{path}?mode=ro',))


def freshFile(path):
    for suffix in ('', '-wal', '-shm', '-journal'):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)


def copyTable(db, schema, table, where=''):
    """Copies one table, and its indexes, from an attached schema into main."""
    sql = db.execute(f"SELECT sql FROM {schema}.sqlite_master WHERE type = 'table' AND name = ?",
                     (table,)).fetchone()
    if sql is None:
        raise PublishRefused(f'{schema} has no table {table}')
    db.execute(sql[0])
    db.execute(f'INSERT INTO main."{table}" SELECT * FROM {schema}."{table}" {where}')
    for (indexSql,) in db.execute(f"SELECT sql FROM {schema}.sqlite_master WHERE type = 'index' "
                                  "AND tbl_name = ? AND sql IS NOT NULL", (table,)).fetchall():
        db.execute(indexSql)


def copyRuns(db, sources):
    """ingestionRuns from each (schema, sourceName), into one table."""
    db.execute('''CREATE TABLE IF NOT EXISTS ingestionRuns (
        sourceDb TEXT NOT NULL, job TEXT NOT NULL, startedAt TEXT NOT NULL, finishedAt TEXT NOT NULL,
        succeeded INTEGER NOT NULL, changes INTEGER, note TEXT)''')
    for schema, name in sources:
        has = db.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE name = 'ingestionRuns'").fetchone()
        if has:
            db.execute(f'INSERT INTO ingestionRuns SELECT ?, job, startedAt, finishedAt, succeeded, changes, note '
                       f'FROM {schema}.ingestionRuns', (name,))


# --- Orbital ------------------------------------------------------------------------

def buildObjects(stagePath, now):
    """Writes orbital_objects + orbital_object_groups (with radio and EIRP
    columns filled) into a fresh staging file. Returns a summary dict."""
    freshFile(stagePath)
    db = connectUri(stagePath)
    attach(db, dbPath(SPACETRACK_DB), 'st')
    db.execute(ORBITAL_TABLE_SQL)
    latestFull = db.execute('SELECT MAX(lastSeenFull) FROM st.gp').fetchone()[0]
    if latestFull is None:
        raise PublishRefused('ingestionSpaceTrack.db has no full pass yet')
    oldest = (now - timedelta(days=MAX_ELEMENT_AGE_DAYS)).strftime('%Y-%m-%dT%H:%M:%S')
    decayedSince = isoDay(now - timedelta(days=RECENT_DECAY_DAYS))
    typeCase = 'CASE g.objectType ' + ' '.join(f"WHEN '{k}' THEN '{v}'" for k, v in OBJECT_TYPES.items()) \
               + ' ELSE g.objectType END'
    with db:
        db.execute(f'''
            INSERT INTO orbital_objects (noradID, name, objectID, epoch, meanMotion, eccentricity, inclination,
                raOfAscNode, argOfPericenter, meanAnomaly, bstar, meanMotionDot, meanMotionDdot, objectType,
                owner, launchDate, launchSite, decayDate, rcsSize, rcsCategory, period, apogee, perigee,
                source, fetchedAt)
            SELECT g.noradID, g.objectName, g.objectID, g.epoch || 'Z', g.meanMotion, g.eccentricity,
                g.inclination, g.raOfAscNode, g.argOfPericenter, g.meanAnomaly, g.bstar, g.meanMotionDot,
                g.meanMotionDdot, {typeCase}, g.countryCode, g.launchDate, g.site, g.decayDate, NULL,
                g.rcsSize, g.period, g.apoapsis, g.periapsis, 'space-track', g.fetchedAt
            FROM st.gp g
            WHERE (g.decayDate IS NULL AND (g.lastSeenFull = ? OR g.fetchedAt >= ?) AND g.epoch >= ?)
               OR (g.decayDate IS NOT NULL AND g.decayDate >= ?)
        ''', (latestFull, latestFull, oldest, decayedSince))
    # EST. SIZE: CelesTrak's radar figure, kept for good once known
    # (ingestionCelesTrak.db satcatRcs; satellites don't change size).
    rcs = 0
    if os.path.exists(dbPath(CELESTRAK_DB)):
        attach(db, dbPath(CELESTRAK_DB), 'ct')
        if db.execute("SELECT 1 FROM ct.sqlite_master WHERE name = 'satcatRcs'").fetchone():
            with db:
                rcs = db.execute('UPDATE orbital_objects SET rcsSize = (SELECT r.rcsM2 FROM ct.satcatRcs r '
                                 'WHERE r.noradID = orbital_objects.noradID) '
                                 'WHERE noradID IN (SELECT noradID FROM ct.satcatRcs)').rowcount
        db.execute('DETACH DATABASE ct')
    summary = {'objects': db.execute('SELECT COUNT(*) FROM orbital_objects').fetchone()[0], 'rcs': rcs}
    db.execute('DETACH DATABASE st')
    db.close()
    return summary


def loadGroupInputs(stagePath):
    """(objects for groupRules, celestrak lists) from the staging file,
    GCAT and ingestionCelesTrak.db."""
    db = connectUri(stagePath, readOnly=True)
    attach(db, dbPath(GCAT_DB), 'gcat')
    objects = [dict(zip(('noradID', 'name', 'objectType', 'launchDate', 'decayDate', 'period', 'inGcat',
                         'ownerCode', 'program', 'category', 'payloadClass', 'massKg', 'tOp'), row))
               for row in db.execute('''
        SELECT o.noradID, o.name, o.objectType, o.launchDate, o.decayDate, o.period, g.noradID IS NOT NULL,
               g.ownerCode, p.program, p.category, p.payloadClass, g.massKg, p.tOp
        FROM orbital_objects o
        LEFT JOIN (SELECT * FROM gcat.gcatObjects WHERE noradID IS NOT NULL GROUP BY noradID) g
               ON g.noradID = o.noradID
        LEFT JOIN gcat.gcatPayloads p ON p.jcat = g.jcat
        GROUP BY o.noradID''')]
    db.close()
    celestrak = {}
    path = dbPath(CELESTRAK_DB)
    if os.path.exists(path):
        ct = connectUri(path, readOnly=True)
        for group, lastSuccess in ct.execute('SELECT groupName, lastSuccess FROM groupFetches '
                                             'WHERE lastSuccess IS NOT NULL'):
            members = {r[0] for r in ct.execute('SELECT noradID FROM groupMembers WHERE groupName = ?', (group,))}
            celestrak[group] = (lastSuccess, members)
        ct.close()
    return objects, celestrak


def storeGroups(stagePath, members):
    db = connectUri(stagePath)
    with db:
        db.execute(GROUPS_TABLE_SQL)
        db.execute('CREATE INDEX idx_orbital_object_groups_group ON orbital_object_groups (groupName)')
        db.executemany('INSERT INTO orbital_object_groups VALUES (?, ?)',
                       [(n, g) for g, ids in members.items() for n in ids])
    db.close()


TX_FIELDS = (('downlinkLow', 'downlink_low'), ('downlinkHigh', 'downlink_high'), ('uplinkLow', 'uplink_low'),
             ('uplinkHigh', 'uplink_high'), ('mode', 'mode'), ('baud', 'baud'), ('status', 'status'),
             ('alive', 'alive'), ('frequencyViolation', 'frequency_violation'),
             ('unconfirmed', 'unconfirmed'), ('updated', 'updated'))
BOOL_FIELDS = {'alive', 'frequency_violation', 'unconfirmed'}


def linkTransmitters(stagePath):
    """Fills the radio columns from SatNOGS. Returns (linked satellites,
    {how: count})."""
    path = dbPath(SATNOGS_DB)
    if not os.path.exists(path):
        return 0, {}
    db = connectUri(stagePath)
    attach(db, path, 'sn')
    rows = db.execute(f'''
        SELECT CASE WHEN x.noradFollowID IN (SELECT noradID FROM orbital_objects) THEN x.noradFollowID END,
               (SELECT o.noradID FROM sn.tle t JOIN orbital_objects o ON o.objectID = t.designator
                 WHERE t.noradID = x.noradID LIMIT 1),
               CASE WHEN x.noradID IN (SELECT noradID FROM orbital_objects) THEN x.noradID END,
               {", ".join("x." + column for column, _ in TX_FIELDS)}
        FROM sn.transmitters x''').fetchall()
    byNorad, how = {}, {}
    for follow, designator, own, *fields in rows:
        norad = follow or designator or own
        if norad is None:
            continue
        way = 'follow' if follow else 'designator' if designator else 'own'
        record = {name: (bool(value) if name in BOOL_FIELDS and value is not None else value)
                  for (_, name), value in zip(TX_FIELDS, fields)}
        byNorad.setdefault(norad, []).append(record)
        how.setdefault(norad, way)
    updates = []
    for norad, records in byNorad.items():
        chosen = choose_rf(records)
        if chosen is not None:
            updates.append((*chosen, norad))
    with db:
        db.executemany("UPDATE orbital_objects SET dlFreqHz = ?, ulFreqHz = ?, dlBandwidthHz = ?, rfMode = ?, "
                       "rfBaud = ?, rfSource = 'satnogs' WHERE noradID = ?", updates)
    db.execute('DETACH DATABASE sn')
    db.close()
    counts = {}
    for _, _, _, _, _, norad in updates:
        counts[how[norad]] = counts.get(how[norad], 0) + 1
    return len(updates), counts


def gcatClasses(objects):
    """{noradID: class} from GCAT for every payload enrichEirp.gcat_class
    can place -- the class tier's fallback while CelesTrak is unavailable."""
    classes = {}
    for o in objects:
        if o['objectType'] == 'PAY':
            cls = enrichEirp.gcat_class(o['category'], o['payloadClass'], o['period'], o['massKg'])
            if cls:
                classes[o['noradID']] = cls
    return classes


def enrichEirpInto(stagePath, fallbackClasses=None):
    db = sqlite3.connect(stagePath)   # implicit transaction: one commit, not one per row
    tagged = enrichEirp.run_eirp_enrichment(db, fallbackClasses)
    db.commit()
    db.close()
    return tagged


def publishOrbital(tmpPath, now, useCelestrak=True):
    stagePath = tmpPath + '.objects'
    try:
        summary = buildObjects(stagePath, now)
        print(f'  objects: {summary["objects"]} from Space-Track, {summary["rcs"]} with a CelesTrak radar figure')

        objects, celestrak = loadGroupInputs(stagePath)
        available = useCelestrak and any(groupRules.celestrakAvailable(lastSuccess, now)
                                         for lastSuccess, _ in celestrak.values())
        members = groupRules.groupMembers(objects, celestrak if useCelestrak else {}, now)
        storeGroups(stagePath, members)
        print(f'  groups: {len(members)} ({", ".join(f"{g} {len(m)}" for g, m in sorted(members.items()) if g in groupRules.RULE_GROUPS)})')
        for group, ours, theirs, both, percent in groupRules.agreement(objects, celestrak, now):
            print(f'    rule {group:13s} ours {ours:6d}  CelesTrak {theirs:6d}  both {both:6d}  agreement {percent:5.1f}%')

        linked, how = linkTransmitters(stagePath)
        print(f'  radio: {linked} satellites with SatNOGS frequencies ({", ".join(f"{k} {v}" for k, v in sorted(how.items()))})')
        # The class tier reads CelesTrak groups; without them, GCAT stands in.
        fallback = None if available else gcatClasses(objects)
        print('  EIRP class tier: ' + ('CelesTrak groups' if available
                                       else f'GCAT (CelesTrak unavailable; {len(fallback)} payloads placed)'))
        enrichEirpInto(stagePath, fallback)

        # Brightness reads GCAT unqualified, so it runs before the trimmed
        # gcatObjects is copied into the site file.
        bright = connectUri(tmpPath)
        try:
            attach(bright, dbPath(GCAT_DB), 'gcat')
            estimateBrightness.refreshBrightness(bright, stagePath)
        finally:
            bright.close()
        if not orbitStats.refreshAll(tmpPath, dbPath(GCAT_DB), stagePath):
            raise PublishRefused('orbitStats could not run')

        db = connectUri(tmpPath)
        attach(db, stagePath, 'stage')
        attach(db, dbPath(GCAT_DB), 'gcat')
        attach(db, dbPath(SPACETRACK_DB), 'st')
        for name, schema in ((SATNOGS_DB, 'sn'), (CELESTRAK_DB, 'ct')):
            if os.path.exists(dbPath(name)):
                attach(db, dbPath(name), schema)
        with db:
            copyTable(db, 'stage', 'orbital_objects')
            copyTable(db, 'stage', 'orbital_object_groups')
            copyTable(db, 'gcat', 'gcatLaunches')
            copyTable(db, 'gcat', 'gcatOrgs')
            db.execute(f'CREATE TABLE gcatObjects AS SELECT {", ".join(GCAT_OBJECT_COLUMNS)} '
                       'FROM gcat.gcatObjects WHERE noradID IS NOT NULL')
            db.execute('CREATE INDEX gcatObjectsByNorad ON gcatObjects (noradID)')
            schemas = [(s, n) for s, n in (('st', 'ingestionSpaceTrack'), ('sn', 'ingestionSatNOGS'),
                                           ('ct', 'ingestionCelesTrak'), ('gcat', 'ingestionGCAT'))
                       if db.execute('SELECT 1 FROM pragma_database_list WHERE name = ?', (s,)).fetchone()]
            copyRuns(db, schemas)
        db.close()
    finally:
        freshFile(stagePath)


# --- Weather ------------------------------------------------------------------------

def stormScale(kpMax):
    """NOAA G level (0 to 5) of a Kp value, thirds included (weatherDerived.gLevel): G1 is 4.67 to 5.33, G5 is 9."""
    return weatherDerived.gLevel(kpMax)


def addDerivedWeather(db):
    """derivedF107ObsClean, derivedF107A81 and derivedStormG, from series already in samples."""
    wd = weatherDerived
    obs = {r[0]: r[1] for r in db.execute("SELECT substr(tsUtc, 1, 10), value FROM samples WHERE series = 'gfzF107Obs'")}
    trios = {}
    for day, quality, value in db.execute(
            "SELECT substr(tsUtc, 1, 10), quality, value FROM swpc.samples WHERE series = 'swpcF107'"):
        trios.setdefault(day, {})[(quality or '').split(' ')[0]] = value
    readings = {day: (t.get('Morning'), t.get('Noon'), t.get('Afternoon')) for day, t in trios.items() if len(t) == 3}
    flagged = wd.f107Bursts(obs, readings)
    for day in flagged:       # the daily value, observed and adjusted, keeps its value and says 'burst?' in the quality column
        db.execute("UPDATE samples SET quality = 'burst?' WHERE series IN ('gfzF107Obs', 'gfzF107Adj') AND tsUtc = ?",
                   (day + 'T00:00:00Z',))
    clean = wd.f107Clean(obs, flagged, readings)
    out = [('derivedF107ObsClean', day + 'T00:00:00Z', value, 'sfu', how) for day, (value, how) in sorted(clean.items())]
    forecast = {r[0]: r[1] for r in db.execute("SELECT substr(tsUtc, 1, 10), value FROM samples WHERE series = 'swpcForecastF107'")}
    for day, (mean, kind) in sorted(wd.f107Centred({d: v for d, (v, _) in clean.items()}, forecast).items()):
        out.append(('derivedF107A81', day + 'T00:00:00Z', mean, 'sfu',
                    'centred 81-day mean of the cleaned observed flux' if kind == 'observed' else
                    'centred 81-day mean, includes the SWPC 45-day forecast'))
    kpTop = db.execute("SELECT substr(tsUtc, 1, 10), MAX(value) FROM samples WHERE series = 'gfzKp' "
                       "AND value IS NOT NULL GROUP BY 1").fetchall()
    out += [('derivedStormG', day + 'T00:00:00Z', float(stormScale(top)), 'G', 'from gfzKp') for day, top in kpTop]
    db.executemany('INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?)', out)


def addScienceDerived(db, nativeCut, hourlyCut):
    """The derived series and events of scripts/weatherDerived.py, from the attached ingestion databases (the
    `swpc` schema) and the tables already copied into the site file."""
    wd = weatherDerived
    # item 3: the Newell function, per minute for the native window, hourly (>= 30 minutes) for the long one
    rows = db.execute("""SELECT v.tsUtc, v.value, y.value, z.value FROM swpc.samples v
        JOIN swpc.samples y ON y.series = 'l1MagByGSM' AND y.tsUtc = v.tsUtc
        JOIN swpc.samples z ON z.series = 'l1MagBzGSM' AND z.tsUtc = v.tsUtc
        WHERE v.series = 'l1WindSpeed' AND v.tsUtc >= ? ORDER BY v.tsUtc""", (hourlyCut,)).fetchall()
    minutes, hourly = wd.newellSeries(rows)
    db.executemany('INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?)',
                   [('derivedNewell', ts, rate, wd.NEWELL_UNIT, 'L1 minute') for ts, rate in minutes if ts >= nativeCut])
    db.executemany('INSERT OR REPLACE INTO samplesHourly VALUES (?, ?, ?, ?, ?)',
                   [('derivedNewell', hour, mean, wd.NEWELL_UNIT, n) for hour, mean, n in hourly])
    events = []
    # item 11: the storm list from GFZ Kp, with DONKI's causal links
    kp = db.execute("SELECT tsUtc, value, quality FROM samples WHERE series = 'gfzKp' ORDER BY tsUtc").fetchall()
    gst = [json.loads(r[0]) for r in db.execute("SELECT json FROM events WHERE eventType = 'GST'")]
    for storm in wd.stormRuns(kp, gst):
        events.append(('storm', storm['startUtc'], storm['startUtc'], storm))
    # item 10: our own S-events from the >10 MeV protons; DONKI's SEP records, one marker per event
    protons = db.execute("SELECT tsUtc, value FROM swpc.samples WHERE series = 'goesProtonGE10MeV' ORDER BY tsUtc").fetchall()
    for event in wd.sEvents(protons):
        events.append(('sEvent', event['startUtc'], event['startUtc'], event))
    sep = [json.loads(r[0]) for r in db.execute("SELECT json FROM events WHERE eventType = 'SEP'")]
    for group in wd.sepGroups(sep):
        events.append(('sepGroup', group['startUtc'], group['key'], group))
    # item 12: the CMEs worth showing (one summary each, from the leading-edge analysis), and a daily count of the rest
    cme = [json.loads(r[0]) for r in db.execute("SELECT json FROM events WHERE eventType = 'CME'")]
    others = {}
    for record in cme:
        if not record.get('activityID') or not record.get('startTime'):
            continue
        if wd.cmeShown(record):
            summary = wd.cmeSummary(record)
            events.append(('cmeShown', record['startTime'][:16] + ':00Z', record['activityID'], summary))
        else:
            others[record['startTime'][:10]] = others.get(record['startTime'][:10], 0) + 1
    days = sorted(r['startTime'][:10] for r in cme if r.get('startTime') and r.get('activityID'))
    if days:
        day = datetime.strptime(days[0], '%Y-%m-%d')
        while day <= datetime.strptime(days[-1], '%Y-%m-%d'):
            key = day.strftime('%Y-%m-%d')
            db.execute('INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?)',
                       ('derivedCmeOtherPerDay', key + 'T00:00:00Z', float(others.get(key, 0)), 'count', 'CMEs not shown'))
            day += timedelta(days=1)
    # item 13: streams seen at L1, shocks at Earth, and the STEREO-A recurrence hints
    hss = [json.loads(r[0]) for r in db.execute("SELECT json FROM events WHERE eventType = 'HSS'")]
    ips = [json.loads(r[0]) for r in db.execute("SELECT json FROM events WHERE eventType = 'IPS'")]
    streams, shocks, recurrence = wd.earthStreams(hss, ips)
    events += [('hssL1', r['eventTime'][:16] + ':00Z', r['hssID'], r) for r in streams if r.get('eventTime') and r.get('hssID')]
    events += [('ipsEarth', r['eventTime'][:16] + ':00Z', r['activityID'], r) for r in shocks
               if r.get('eventTime') and r.get('activityID')]
    events += [('hssRecurrence', r['seenUtc'], r['hssID'], r) for r in recurrence]
    # item 9: the largest flare of each UT day, from the primary GOES satellite only
    primary = db.execute("SELECT quality FROM swpc.samples WHERE series = 'goesXrayLong' ORDER BY tsUtc DESC LIMIT 1").fetchone()
    number = re.search(r'GOES-(\d+)', primary[0] or '') if primary else None
    if number:
        xra = [json.loads(r[0]) for r in db.execute("SELECT json FROM events WHERE eventType = 'XRA'")]
        for day, (flux, cls, peak) in sorted(wd.dailyFlareMax(xra, 'G' + number.group(1)).items()):
            db.execute('INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?)',
                       ('derivedFlareMaxDay', day + 'T00:00:00Z', flux, 'W/m2', f'{cls} peak {peak} GOES-{number.group(1)}'))
    db.executemany('INSERT OR REPLACE INTO events VALUES (?, ?, ?, ?)',
                   [(kind, start, eid, json.dumps(rec, sort_keys=True, ensure_ascii=False)) for kind, start, eid, rec in events])


def publishWeather(tmpPath, now):
    opened = []
    try:
        _buildWeather(tmpPath, now, opened)
    finally:
        for db in opened:      # a failed build must not leave the temporary file locked (Windows)
            try:
                db.close()
            except sqlite3.Error:
                pass


def _buildWeather(tmpPath, now, opened):
    swpcPath = dbPath(SWPC_DB)
    if not os.path.exists(swpcPath):
        raise PublishRefused(f'{SWPC_DB} not found')
    sources = [('swpc', SWPC_DB, 'ingestionSWPC')] + [(s, f, n) for s, f, n in (
        ('gfz', GFZ_DB, 'ingestionGFZ'), ('donki', DONKI_DB, 'ingestionDONKI'), ('gcr', GCR_DB, 'ingestionGCR'),
        ('silso', SILSO_DB, 'ingestionSILSO'), ('tec', TEC_DB, 'ingestionTEC')) if os.path.exists(dbPath(f))]
    nativeCut = (now - timedelta(days=WEATHER_NATIVE_DAYS)).strftime('%Y-%m-%dT%H:%M:%SZ')
    hourlyCut = (now - timedelta(days=WEATHER_HOURLY_DAYS)).strftime('%Y-%m-%dT%H:00:00Z')
    fast = ' OR '.join(f"series LIKE '{p}%'" for p in HIGH_RATE_PREFIXES)
    db = connectUri(tmpPath)
    opened.append(db)
    with db:
        db.executescript('''
            CREATE TABLE samples (series TEXT NOT NULL, tsUtc TEXT NOT NULL, value REAL, unit TEXT, quality TEXT,
                                  PRIMARY KEY (series, tsUtc)) WITHOUT ROWID;
            CREATE TABLE samplesHourly (series TEXT NOT NULL, tsUtc TEXT NOT NULL, value REAL, unit TEXT,
                                        readings INTEGER, PRIMARY KEY (series, tsUtc)) WITHOUT ROWID;
            CREATE TABLE events (eventType TEXT NOT NULL, startUtc TEXT, eventID TEXT NOT NULL, json TEXT NOT NULL,
                                 PRIMARY KEY (eventType, eventID)) WITHOUT ROWID;
            CREATE INDEX eventsByStart ON events (eventType, startUtc);
            CREATE TABLE latestMaps (name TEXT PRIMARY KEY, tsUtc TEXT NOT NULL, json TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE tecMaps (source TEXT NOT NULL, product TEXT NOT NULL, issuedUtc TEXT NOT NULL, validUtc TEXT NOT NULL,
                                  kind TEXT NOT NULL, gz BLOB NOT NULL, PRIMARY KEY (source, product, issuedUtc, validUtc)) WITHOUT ROWID;
            CREATE INDEX tecMapsByValid ON tecMaps (source, validUtc);
        ''')
    for schema, file, _ in sources:
        attach(db, dbPath(file), schema)
    with db:
        for schema, _, _ in sources:
            # swpcKp1m is a sawtooth that restarts every 3-hour block: only its latest value is published
            db.execute(f"INSERT OR REPLACE INTO samples SELECT series, tsUtc, value, unit, quality FROM {schema}.samples "
                       f"WHERE series != 'swpcKp1m' AND (NOT ({fast}) OR tsUtc >= ?)", (nativeCut,))
            db.execute(f"INSERT OR REPLACE INTO samples SELECT series, tsUtc, value, unit, quality FROM {schema}.samples "
                       f"WHERE series = 'swpcKp1m' AND tsUtc = (SELECT MAX(tsUtc) FROM {schema}.samples WHERE series = 'swpcKp1m')")
            minimum = ' '.join(f"WHEN series LIKE '{p}%' THEN {n}" for p, n in HOURLY_MIN_READINGS if p) + f' ELSE {HOURLY_MIN_READINGS[-1][1]}'
            db.execute(f"INSERT OR REPLACE INTO samplesHourly SELECT series, substr(tsUtc, 1, 13) || ':00:00Z', "
                       f'AVG(value), MIN(unit), COUNT(value) FROM {schema}.samples WHERE ({fast}) AND tsUtc >= ? '
                       f'GROUP BY series, substr(tsUtc, 1, 13) HAVING COUNT(value) >= CASE {minimum} END', (hourlyCut,))
            db.execute(f'INSERT OR IGNORE INTO events SELECT eventType, startUtc, eventID, json FROM {schema}.events')
            if db.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE name = 'latestMaps'").fetchone():
                db.execute(f'INSERT OR REPLACE INTO latestMaps SELECT name, tsUtc, json FROM {schema}.latestMaps')
            if db.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE name = 'tecMaps'").fetchone():
                db.execute(f'INSERT OR REPLACE INTO tecMaps SELECT source, product, issuedUtc, validUtc, kind, gz FROM {schema}.tecMaps')
        addDerivedWeather(db)
        addScienceDerived(db, nativeCut, hourlyCut)
        copyRuns(db, [(schema, name) for schema, _, name in sources])
    db.close()


# --- Other types ----------------------------------------------------------------------

def publishCopy(tmpPath, sourceDb, tables, runsName=None):
    db = connectUri(tmpPath)
    attach(db, dbPath(sourceDb), 'src')
    with db:
        for table in tables:
            copyTable(db, 'src', table)
        if runsName:
            copyRuns(db, [('src', runsName)])
    db.close()


TYPES = {
    'orbital': SITE_ORBITAL_DB,
    'news': SITE_NEWS_DB,
    'sky': SITE_SKY_DB,
    'groundSegment': SITE_GROUND_SEGMENT_DB,
    'weather': SITE_WEATHER_DB,
}


def build(kind, tmpPath, now, useCelestrak):
    if kind == 'orbital':
        publishOrbital(tmpPath, now, useCelestrak)
    elif kind == 'news':
        publishCopy(tmpPath, NEWS_DB, ('articles', 'articleTopics', 'newsTopicCounts'), 'ingestionNews')
    elif kind == 'sky':
        src = connectUri(dbPath(SKY_DB), readOnly=True)
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                            "AND name NOT LIKE 'sqlite_%'")]
        src.close()
        publishCopy(tmpPath, SKY_DB, tables)
    elif kind == 'groundSegment':
        publishCopy(tmpPath, GROUND_SEGMENT_DB, ('ground_segment_assets',))
    elif kind == 'weather':
        publishWeather(tmpPath, now)


def check(kind, tmpPath, livePath, force):
    db = connectUri(tmpPath, readOnly=True)
    result = db.execute('PRAGMA integrity_check').fetchone()[0]
    if result != 'ok':
        raise PublishRefused(f'integrity check: {result}')
    counts = {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in SANITY_TABLES[kind]}
    db.close()
    if any(n == 0 for n in counts.values()):
        raise PublishRefused(f'empty table: {counts}')
    if os.path.exists(livePath) and not force:
        live = connectUri(livePath, readOnly=True)
        for table, n in counts.items():
            try:
                old = live.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except sqlite3.OperationalError:
                continue
            if old and n < old * (1 - MAX_DROP):
                live.close()
                raise PublishRefused(f'{table} would drop from {old} to {n} rows (over {MAX_DROP:.0%}); '
                                     'use --force if that is right')
        live.close()
    return counts


def recordPublish(tmpPath, kind, startedAt, counts):
    """The publish itself, as a run in the file's ingestionRuns -- the
    freshness table's 'last refresh' for data computed here (EIRP)."""
    db = sqlite3.connect(tmpPath)
    with db:
        copyRuns(db, [])
        db.execute('INSERT INTO ingestionRuns VALUES (?, ?, ?, ?, 1, ?, NULL)',
                   ('publishSite', 'publish' + kind[0].upper() + kind[1:], startedAt,
                    utcNow().strftime('%Y-%m-%dT%H:%M:%SZ'), next(iter(counts.values()))))
    db.execute('VACUUM')
    db.close()


def publish(kind, now=None, useCelestrak=True, force=False):
    """Builds, checks and swaps in one site file. Returns its row counts."""
    now = now or utcNow()
    startedAt = utcNow().strftime('%Y-%m-%dT%H:%M:%SZ')
    livePath = dbPath(TYPES[kind])
    tmpPath = livePath + '.tmp'
    freshFile(tmpPath)
    try:
        build(kind, tmpPath, now, useCelestrak)
        counts = check(kind, tmpPath, livePath, force)
        recordPublish(tmpPath, kind, startedAt, counts)
        if os.path.exists(livePath):
            shutil.copy2(livePath, livePath + '.prev')
        os.replace(tmpPath, livePath)
    finally:
        freshFile(tmpPath)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build and swap in the website databases (site<Type>.db).')
    parser.add_argument('kind', choices=list(TYPES) + ['all'])
    parser.add_argument('--no-celestrak', action='store_true', help='groups from our own rules only')
    parser.add_argument('--force', action='store_true', help='publish even if the sanity check objects')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    failed = False
    for kind in (TYPES if args.kind == 'all' else [args.kind]):
        started = time.time()
        print(f'\n=== [{time.strftime("%H:%M:%S")}] publish {kind} ===')
        try:
            counts = publish(kind, useCelestrak=not args.no_celestrak, force=args.force)
            size = os.path.getsize(dbPath(TYPES[kind])) / 1e6
            print(f'  OK -- {TYPES[kind]} {size:.1f} MB in {time.time() - started:.1f} s; '
                  + ', '.join(f'{t} {n}' for t, n in counts.items()))
        except (PublishRefused, sqlite3.Error, OSError) as error:
            failed = True
            print(f'  REFUSED -- {type(error).__name__}: {error}; {TYPES[kind]} left as it was')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
