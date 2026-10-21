"""Publish step: builds the databases the website reads (site<Type>.db)
from the ingestion databases, and swaps each one into place whole.

Step 9 of 0_documentation/dbRefactorPlan.md.

    python scripts/publishSite.py orbital|news|sky|groundSegment|all
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

EST. SIZE (rcsSize) is CelesTrak's radar cross-section in m^2, kept for
good once known (ingestionCelesTrak.db satcatRcs; decided 2026-10-21:
satellites don't change size). Space-Track's SMALL / MEDIUM / LARGE is
published alongside as rcsCategory.
"""

import argparse
import os
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
from dbPaths import (CELESTRAK_DB, GCAT_DB, GROUND_SEGMENT_DB, NEWS_DB, SATNOGS_DB, SITE_GROUND_SEGMENT_DB,
                     SITE_NEWS_DB, SITE_ORBITAL_DB, SITE_SKY_DB, SKY_DB, SPACETRACK_DB, dbPath)
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
}


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
