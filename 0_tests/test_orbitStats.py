"""Tests for scripts/orbitStats.py -- the ON-ORBIT overview's precomputed
figures. In-memory databases only: a stats DB with stand-in 'gcat' and
'orb' sources attached, never the real files.

Run with:  pytest 0_tests/ -v
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import orbitStats  # noqa: E402


def sources():
    """A stats DB with in-memory 'gcat' and 'orb' attached, minimal schemas."""
    db = sqlite3.connect(':memory:')
    db.execute("ATTACH DATABASE ':memory:' AS gcat")
    db.execute("ATTACH DATABASE ':memory:' AS orb")
    db.execute('CREATE TABLE gcat.gcatObjects (jcat TEXT, noradID INTEGER, owners TEXT, stateCode TEXT, '
               'manufacturer TEXT, bus TEXT, launchTag TEXT, parent TEXT)')
    db.execute('CREATE TABLE gcat.gcatLaunches (launchTag TEXT, launchVehicle TEXT)')
    db.execute('CREATE TABLE gcat.gcatParents (jcat TEXT, name TEXT, coarseType TEXT, launchDate TEXT, '
               'decayDate TEXT, owners TEXT, stateCode TEXT)')
    db.execute('CREATE TABLE gcat.gcatPayloads (jcat TEXT, category TEXT, payloadClass TEXT)')
    db.execute('CREATE TABLE gcat.gcatOrgs (code TEXT, shortName TEXT, name TEXT, orgClass TEXT, stateCode TEXT)')
    db.execute('CREATE TABLE orb.orbital_objects (noradID INTEGER, name TEXT, objectType TEXT, decayDate TEXT, '
               'perigee REAL, apogee REAL, inclination REAL, launchDate TEXT, epoch TEXT, meanMotion REAL, '
               'raOfAscNode REAL, argOfPericenter REAL, meanAnomaly REAL, downlinkBand TEXT)')
    db.execute('CREATE TABLE orb.orbital_object_groups (noradID INTEGER, groupName TEXT)')
    return db


def add(db, norad, name='SAT', orbit=(500, 520), objectType='PAY', decayed=False, groups=(),
        gcat=True, owners='X', state='US', category='COM', inclination=53.0, payloadClass='B', parent=None):
    """One catalogued object; gcat=False leaves it unmatched in GCAT."""
    db.execute('INSERT INTO orb.orbital_objects (noradID, name, objectType, decayDate, perigee, apogee, '
               'inclination, launchDate) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
               (norad, name, objectType, '2020-01-01' if decayed else None, *(orbit or (None, None)),
                inclination, '2019-05-24'))
    for group in groups:
        db.execute('INSERT INTO orb.orbital_object_groups VALUES (?, ?)', (norad, group))
    if gcat:
        db.execute('INSERT INTO gcat.gcatObjects (jcat, noradID, owners, stateCode, manufacturer, bus, parent) '
                   'VALUES (?, ?, ?, ?, ?, ?, ?)', (f'S{norad:05d}', norad, owners, state, 'MAKER', 'BUS-1', parent))
        db.execute('INSERT INTO gcat.gcatPayloads VALUES (?, ?, ?)', (f'S{norad:05d}', category, payloadClass))


def regimes(db, status, kind):
    return {regime: counts for (s, k, regime, _, *counts) in orbitStats.storeRegimes(db)
            if s == status and k == kind}


def sample():
    db = sources()
    add(db, 1, 'STARLINK-1001', (460, 480), groups=('active', 'starlink'), owners='SPXS')   # LEO, SpaceX
    add(db, 2, 'NASA SAT', (400, 420), groups=('active',), owners='NASA')                  # VLEO
    add(db, 3, 'GPS', (20100, 20300), groups=('active',), owners='USSF')                   # MEO
    add(db, 4, 'DEAD GEO', (35780, 35800), owners='INTL')                                  # GEO, inactive
    add(db, 5, 'ISS (ZARYA)', (410, 420), groups=('active', 'stations'), category='SS')    # station
    add(db, 6, 'CREW DRAGON 12', (410, 420), groups=('active', 'stations'), gcat=False)    # station visitor, no GCAT
    add(db, 7, 'KNACKSAT-2', (405, 415), groups=('active', 'stations'), category='TECH')   # ISS-released cubesat
    add(db, 8, 'CALSPHERE 1', (1000, 1100), category='CAL')                              # passive
    add(db, 9, 'NO ORBIT', None, groups=('active',))                                      # unclassified
    add(db, 10, 'R/B', (500, 520), objectType='R/B')                                     # not a payload
    add(db, 11, 'GONE', (400, 420), decayed=True, groups=('active',))                    # decayed
    return db


def test_all_spacecraft_counts_every_payload_by_current_orbit():
    db = sample()
    counts = regimes(db, 'all', 'spacecraft')
    assert counts['VLEO'] == [4, 4]     # NASA SAT, ISS, Crew Dragon, KnackSat-2 -- none from SpaceX
    assert counts['LEO'] == [2, 1]      # Starlink (SpaceX) and Calsphere
    assert counts['MEO'] == [1, 1]
    assert counts['GEO'] == [1, 1]
    assert counts['unclassified'] == [1, 1]


def test_satellites_drop_stations_visitors_and_passive_objects_but_not_cubesats():
    db = sample()
    counts = regimes(db, 'all', 'satellites')
    assert counts['VLEO'] == [2, 2]     # NASA SAT and KnackSat-2 stay; ISS and Crew Dragon go
    assert counts['LEO'] == [1, 0]      # Calsphere goes; Starlink stays


def test_active_uses_celestrak_active_group():
    db = sample()
    counts = regimes(db, 'active', 'satellites')
    assert counts['GEO'] == [0, 0]      # the dead GEO satellite isn't in 'active'
    assert counts['VLEO'] == [2, 2]
    assert counts['LEO'] == [1, 0]


def test_vleo_boundary_is_450km():
    assert orbitStats.orbitRegime(440, 455) == 'VLEO'    # mean 447.5
    assert orbitStats.orbitRegime(445, 455) == 'LEO'     # mean 450


def test_heo_is_classified_by_eccentricity_before_altitude():
    assert orbitStats.orbitRegime(500, 40000) == 'HEO'      # Molniya: mean ~20,000 km would be MEO
    assert orbitStats.orbitRegime(250, 35786) == 'HEO'      # geostationary transfer orbit
    assert orbitStats.orbitRegime(16000, 133000) == 'HEO'   # Chandra-like: mean would be > GEO
    assert orbitStats.orbitRegime(36000, 36300) == '> GEO'  # near-circular graveyard orbit
    assert orbitStats.orbitRegime(20100, 20300) == 'MEO'    # GPS stays MEO


def test_heo_threshold_is_0_25():
    # e = (ra - rp) / (ra + rp): perigee 1,000 km, apogee chosen either side of 0.25
    rp = 1000 + orbitStats.EARTH_EQUATORIAL_RADIUS_KM
    apogeeAt025 = rp * 1.25 / 0.75 - orbitStats.EARTH_EQUATORIAL_RADIUS_KM
    assert orbitStats.orbitRegime(1000, apogeeAt025 - 1) != 'HEO'
    assert orbitStats.orbitRegime(1000, apogeeAt025 + 1) == 'HEO'


def test_heo_column_comes_last():
    assert orbitStats.REGIMES[-2:] == ['> GEO', 'HEO']


def test_nationality_splits_us_and_groups_others(monkeypatch):
    monkeypatch.setattr(orbitStats, 'NATIONALITY_TOP_STATES', 2)
    db = sources()
    for norad, (state, name) in enumerate([('US', 'STARLINK-1'), ('US', 'STARLINK-2'), ('US', 'GPS IIF-1'),
                                           ('CN', 'YAOGAN 1'), ('CN', 'YAOGAN 2'), ('F', 'PLEIADES 1'),
                                           ('I-ESA', 'SENTINEL-2A')], start=1):
        add(db, norad, name, state=state)
    add(db, 50, 'UNMATCHED', gcat=False)                       # no GCAT state: counted in Other
    db.execute("INSERT INTO gcat.gcatOrgs VALUES ('CN', 'China', 'China, People''s Republic of', 'C', 'CN')")
    rows = [row[4:] for row in orbitStats.storeNationality(db) if row[:3] == ('all', 'spacecraft', 'with')]
    assert rows == [
        ('United States – Starlink', 'US', 2),
        ('United States – Other', 'US', 1),
        ('China', 'CN', 2),
        ('European Space Agency', 'I-ESA', 1),          # always shown, though outside the top 2
        ('Other (1 countries & organisations)', None, 2),
    ]


def test_inclination_buckets_are_5_degrees_lower_edge_inclusive():
    assert orbitStats.inclinationBucket(0) == 0
    assert orbitStats.inclinationBucket(4.999) == 0
    assert orbitStats.inclinationBucket(5) == 5
    assert orbitStats.inclinationBucket(53.05) == 50
    assert orbitStats.inclinationBucket(97.6) == 95
    assert orbitStats.inclinationBucket(180) == 175     # 180 goes in the last bucket
    assert orbitStats.inclinationBucket(None) is None


def test_inclination_histogram_stores_every_bucket_and_the_unknowns():
    db = sources()
    add(db, 1, inclination=53.0)
    add(db, 2, inclination=53.2)
    add(db, 3, inclination=97.6)
    add(db, 4, inclination=None)
    rows = [row[3:] for row in orbitStats.storeInclination(db) if row[:3] == ('all', 'spacecraft', 'with')]
    buckets = {start: n for start, end, n in rows}
    assert len(rows) == 36 + 1                          # 0-5 ... 175-180, plus no inclination
    assert buckets[50] == 2 and buckets[95] == 1 and buckets[None] == 1
    assert sum(buckets.values()) == 4
    assert (0, 5, 0) in rows and (175, 180, 0) in rows  # empty buckets kept


def test_without_spacex_drops_spacex_payloads_from_every_chart():
    db = sample()
    nationality = [row[4:] for row in orbitStats.storeNationality(db) if row[:3] == ('all', 'spacecraft', 'without')]
    assert not any(label.endswith('Starlink') for label, _, _ in nationality)   # empty row dropped
    assert sum(n for _, _, n in nationality) == 8      # 9 payloads in orbit minus the Starlink
    inclination = [row[3:] for row in orbitStats.storeInclination(db) if row[:3] == ('all', 'spacecraft', 'without')]
    withSpacex = [row[3:] for row in orbitStats.storeInclination(db) if row[:3] == ('all', 'spacecraft', 'with')]
    assert sum(n for *_, n in withSpacex) - sum(n for *_, n in inclination) == 1


def test_sector_uses_payload_class_then_owner_class():
    orgs = {'NASA': 'C', 'NRO': 'D'}
    assert orbitStats.payloadSector('S1', 'B', 'NASA', orgs) == 'B'     # payload's own class wins
    assert orbitStats.payloadSector('S1', None, 'NRO/NASA', orgs) == 'D'  # else first owner's
    assert orbitStats.payloadSector('S1', 'CB', 'X', orgs) == 'C'       # dual class: first letter
    assert orbitStats.payloadSector('S1', None, 'X', orgs) is None      # no class anywhere
    assert orbitStats.payloadSector(None, 'B', 'NASA', orgs) is None    # no GCAT match


def test_sector_pie_counts_every_payload_once():
    db = sources()
    add(db, 1, payloadClass='A')
    add(db, 2, payloadClass='D')
    add(db, 3, payloadClass='D')
    add(db, 4, gcat=False)
    rows = {row[3]: row[5] for row in orbitStats.storeSector(db) if row[:3] == ('all', 'spacecraft', 'with')}
    assert rows == {'A': 1, 'B': 0, 'C': 0, 'D': 2, 'unknown': 1}


def test_owners_ranked_by_first_owner_with_no_owner_row():
    db = sources()
    add(db, 1, owners='PLAN')
    add(db, 2, owners='PLAN/NASA')       # first owner only
    add(db, 3, owners='NASA')
    add(db, 4, gcat=False)
    db.execute("INSERT INTO gcat.gcatOrgs VALUES ('PLAN', 'Planet', 'Planet Labs, Inc.', 'B', 'US')")
    rows = [(r[3], r[4], r[5], r[8]) for r in orbitStats.storeOwners(db) if r[:3] == ('all', 'spacecraft', 'with')]
    assert rows == [(1, 'PLAN', 'Planet', 2), (2, 'NASA', 'NASA', 1), (0, None, 'No owner on file', 1)]


def test_all_objects_adds_rocket_bodies_and_debris():
    db = sample()
    spacecraft = regimes(db, 'all', 'spacecraft')
    objects = regimes(db, 'all', 'objects')
    assert objects['LEO'][0] == spacecraft['LEO'][0] + 1     # the R/B at 500-520 km
    assert regimes(db, 'active', 'objects') == regimes(db, 'active', 'spacecraft')   # only payloads are active


def test_kind_toggle_has_three_settings():
    assert orbitStats.KIND_FILTERS == ['satellites', 'spacecraft', 'objects']


def launchHistorySources():
    db = sources()
    db.execute('ALTER TABLE gcat.gcatObjects ADD COLUMN name TEXT')
    for column in ('launchDate', 'decayDate', 'status', 'coarseType'):
        db.execute(f'ALTER TABLE gcat.gcatObjects ADD COLUMN {column} TEXT')
    db.execute('CREATE TABLE gcat.gcatDecays (year INTEGER, coarseType TEXT, status TEXT, spacex INTEGER, '
               'objects INTEGER)')
    return db


def gcatPayload(db, jcat, name, launched, decayed=None, status='O', owners='X', payloadClass='C'):
    db.execute('INSERT INTO gcat.gcatObjects (jcat, owners, name, launchDate, decayDate, status, coarseType) '
               "VALUES (?, ?, ?, ?, ?, ?, 'P')", (jcat, owners, name, launched, decayed, status))
    db.execute('INSERT INTO gcat.gcatPayloads VALUES (?, ?, ?)', (jcat, 'COM', payloadClass))


def test_payloads_launched_counts_new_payloads_by_launch_year():
    db = launchHistorySources()
    gcatPayload(db, 'S1', 'Sat 1', '2000-03-01', payloadClass='D')
    gcatPayload(db, 'S2', 'Sat 2', '2000-06-01', decayed='2001-05-01', payloadClass='D')
    gcatPayload(db, 'S3', 'Starlink-1', '2001-01-05', owners='SPXS', payloadClass='B')
    gcatPayload(db, 'S4', 'Failed', '2000-01-01', decayed='2000-01-01', status='N')
    stored = orbitStats.payloadsLaunchedByYear(db, today='2002-06-30')
    rows = {(y, s): n for f, y, s, _, n in stored if f == 'with'}
    without = {(y, s): n for f, y, s, _, n in stored if f == 'without'}
    assert without[(2001, 'B')] == 0 and without[(2000, 'D')] == 2   # the SpaceX-owned Starlink goes
    assert rows[(2000, 'D')] == 2                                    # both 2000 launches, decayed or not
    assert rows[(2001, 'B')] == 1 and rows[(2001, 'D')] == 0         # Starlink counts as commercial
    assert sum(n for (y, _), n in rows.items() if y == 2002) == 0    # years run to this one
    assert sum(rows.values()) == 3                                   # the launch failure left out


def test_reentries_count_only_objects_that_came_back_down():
    db = launchHistorySources()
    db.executemany('INSERT INTO gcat.gcatDecays VALUES (?, ?, ?, ?, ?)', [
        (2025, 'P', 'R', 0, 100), (2025, 'P', 'R', 1, 800), (2025, 'P', 'D', 0, 50), (2025, 'R', 'R', 1, 40),
        (2025, 'D', 'R', 0, 300), (2025, 'C', 'R', 0, 5), (2025, 'P', 'E', 0, 3), (2025, 'P', 'DK', 0, 7),
        (2025, 'P', 'L', 0, 10)])
    stored = orbitStats.reentriesByYear(db)
    rows = {k: n for f, _, k, _, n in stored if f == 'with'}
    assert rows == {'P': 960, 'R': 40, 'D': 300, 'other': 5}   # departures and dockings not counted
    without = {k: n for f, _, k, _, n in stored if f == 'without'}
    assert without == {'P': 160, 'R': 0, 'D': 300, 'other': 5}   # SpaceX-owned objects left out


def test_mission_category_groups():
    assert orbitStats.categoryGroup('COM') == 'COM'
    assert orbitStats.categoryGroup('IMG-R') == 'IMG'          # radar imaging is imaging
    assert orbitStats.categoryGroup('SIG?*') == 'SIG'          # uncertainty marks dropped
    assert orbitStats.categoryGroup('EW') == 'SIG'
    assert orbitStats.categoryGroup('COM/TECH') == 'COM'       # first category listed
    assert orbitStats.categoryGroup('SS') == 'SS'
    assert orbitStats.categoryGroup('CAL') == 'other'
    assert orbitStats.categoryGroup(None) is None


def test_geo_longitude_from_elements():
    from datetime import datetime, timezone
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # GMST at that epoch is about 100.6 deg; node + perigee + anomaly 110.6 -> about 10 E.
    lon = orbitStats.geoLongitude('2026-01-01T00:00:00Z', orbitStats.SIDEREAL_REVS_PER_DAY,
                                  50.0, 30.0, 30.6, now=epoch)
    assert abs(lon - 10.0) < 0.5
    # A satellite drifting 1 deg/day east has moved 10 deg after ten days.
    drifting = orbitStats.SIDEREAL_REVS_PER_DAY + 1 / 360
    later = orbitStats.geoLongitude('2026-01-01T00:00:00Z', drifting, 50.0, 30.0, 30.6,
                                    now=datetime(2026, 1, 11, tzinfo=timezone.utc))
    assert abs(later - lon - 10.0) < 0.01
    assert orbitStats.geoLongitude(None, 1.0, 0, 0, 0) is None


def test_object_table_has_a_row_per_object_in_orbit():
    db = sample()
    rows = orbitStats.storeObjectTable(db)
    assert len(rows) == 10                                      # 11 objects, one decayed
    starlink = next(r for r in rows if r[0] == 1)
    assert starlink[1:5] == (1, 1, 1, 1)                        # active, payload, satellite, spacex
    assert starlink[5] == 'LEO' and starlink[16] == 2019        # regime, launch year
    rocket = next(r for r in rows if r[0] == 10)
    assert rocket[2:4] == (0, 0)                                # not a payload, not a satellite


def test_object_table_records_type_and_debris_parent():
    db = sources()
    add(db, 1, 'FENGYUN 1C DEB', objectType='DEB', parent='S25730', category=None)
    add(db, 2, 'CZ-6A R/B', objectType='R/B')
    add(db, 3, 'UNTYPED', objectType=None)
    db.execute("INSERT INTO gcat.gcatParents VALUES ('S25730', 'Fengyun-1C', 'P', '1999-05-10', NULL, 'CMA', 'CN')")
    rows = {r[0]: r for r in orbitStats.storeObjectTable(db)}
    assert rows[1][18] == 'DEB' and rows[1][20:23] == ('S25730', 'Fengyun-1C', 1999)
    assert rows[2][18] == 'R/B' and rows[3][18] == 'UNK'


def test_debris_in_orbit_is_created_so_far_less_reentered_so_far():
    db = sources()
    db.execute('CREATE TABLE gcat.gcatDebrisYears (year INTEGER, spacex INTEGER, created INTEGER, reentered INTEGER)')
    db.executemany('INSERT INTO gcat.gcatDebrisYears VALUES (?, ?, ?, ?)', [
        (2000, 0, 100, 0), (2001, 0, 0, 30), (2001, 1, 50, 0), (2003, 1, 0, 20)])
    rows = {(f, y): (c, r, n) for f, y, c, r, n in orbitStats.debrisByYear(db)}
    assert rows[('with', 2000)] == (100, 0, 100)
    assert rows[('with', 2001)] == (50, 30, 120)
    assert rows[('with', 2002)] == (0, 0, 120)          # years with nothing still listed
    assert rows[('with', 2003)] == (0, 20, 100)
    assert rows[('without', 2003)] == (0, 0, 70)       # SpaceX-owned pieces left out


def test_every_filter_combination_is_stored():
    db = sample()
    orbitStats.storeRegimes(db)
    combos = set(db.execute('SELECT DISTINCT statusFilter, kindFilter FROM onOrbitRegimes').fetchall())
    assert combos == {(status, kind) for status in ('active', 'all')
                      for kind in ('satellites', 'spacecraft', 'objects')}


def test_refresh_skips_when_a_source_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(orbitStats, 'GCAT_DB', str(tmp_path / 'missing.db'))
    assert orbitStats.refreshAll() is False
