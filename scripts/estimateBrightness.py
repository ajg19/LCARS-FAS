"""Estimates the standard magnitude of every payload in orbit -- satellites,
operational or defunct, and space stations -- and every rocket body (spent
stages, among the brighter objects in the sky) into ingestionDBs/gcat.db
table gcatBrightness, for GRD VIEW. Debris and unknown objects are
deliberately not estimated: they get no row.

Run after every GCAT ingestion (ingestGcat.py calls it), as it works from
GCAT's sizes and bus types. Safe to run by hand.

Standard magnitude: how bright the object would look 1,000 km away -- the
usual satellite convention (strictly, half lit; the measured Starlink
values are means over observed lighting). The browser adjusts it for the
real distance and lighting at the moment.

The objects are those in the tracked catalogue (orbitalObjects.db, not
decayed, catalogue type PAY or R/B) -- the objects GRD VIEW plots -- with sizes
and bus types from GCAT, matched by NORAD number. (GCAT's own Status is
not used to decide what is in orbit: its GRP and ATT codes cover both
objects still up, like the ISS and Hubble, and long-gone ones.)

Each gets a value and a source, best first:
    station    the composite space stations, which GCAT lists module by
               module (the tracked object carries one module's size, so a
               size estimate is far too faint): ISS -1.3 (observers'
               published standard magnitude); Tiangong 0.0 (estimate:
               observed about 1-1.5 magnitudes fainter than the ISS)
    starlink   by design generation (STARLINK_CLASSES), from GCAT's bus
               type and, within the first-generation bus, launch date --
               means of measured 1,000-km magnitudes (Mallama et al.):
                   v1.0 original   to 2020-07          5.89
                   VisorSat        2020-08 to 2021-08  7.21
                   v1.5            from 2021-09        6.34
                   V2 Mini (V2M, and its V2MD direct-to-cell and V2MO
                   optimised variants, not measured separately)  7.22
               Starlinks not yet in GCAT (the newest launches), from 2023
               on, are taken to be V2 Minis ('V2 Mini (assumed)').
    size       from GCAT's length, diameter and span, as a diffusely
               reflecting body of assumed reflectivity (albedo ALBEDO):
               projected body area plus half the area of any panels (span
               beyond the body), as panels are often edge-on. Span is
               capped at MAX_SPAN_RATIO x the body, as GCAT's span includes
               wire antennas and tethers (IMAGE's is 500 m). About +/- 1
               magnitude.
    default    no size, or not in GCAT: DEFAULT_MAGNITUDE by type

Table gcatBrightness: noradID PRIMARY KEY, stdMag, source -- replaced whole
in one transaction on each run.
"""

import math
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'ingestionDBs', 'gcat.db')
ORBITAL_DB_PATH = os.path.join(BASE_DIR, 'ingestionDBs', 'orbitalObjects.db')

SUN_MAGNITUDE = -26.74
ALBEDO = 0.25
STANDARD_RANGE_M = 1.0e6     # 1,000 km
MAX_SPAN_RATIO = 5
DEFAULT_MAGNITUDE = {'PAY': 7.0, 'R/B': 6.0}   # by catalogue type
STATIONS = {25544: -1.3, 48274: 0.0}   # ISS (Zarya), Tiangong (Tianhe)

# (GCAT bus, launched on or after, launched before, standard magnitude, class)
STARLINK_CLASSES = (
    ('Starlink V2M', None, None, 7.22, 'V2 Mini'),
    ('Starlink V2MD', None, None, 7.22, 'V2 Mini DTC'),
    ('Starlink V2MO', None, None, 7.22, 'V2 Mini Optimised'),
    ('Starlink', None, '2020-08-01', 5.89, 'v1.0'),
    ('Starlink', '2020-08-01', '2021-09-01', 7.21, 'VisorSat'),
    ('Starlink', '2021-09-01', None, 6.34, 'v1.5'),
    (None, '2020-08-01', '2021-09-01', 7.21, 'VisorSat'),   # GCAT has no bus for a few of these
    # Not yet in GCAT (the newest launches): every Starlink launched since
    # 2023 is a V2 Mini variant.
    (None, '2023-02-01', None, 7.22, 'V2 Mini (assumed)'),
)


def starlinkMagnitude(bus, launchDate):
    """(standard magnitude, class) for a Starlink, or None if unclassified."""
    for classBus, start, end, magnitude, label in STARLINK_CLASSES:
        if bus != classBus:
            continue
        if start and (not launchDate or launchDate < start):
            continue
        if end and (not launchDate or launchDate >= end):
            continue
        return magnitude, label
    return None


def sizeMagnitude(lengthM, diameterM, spanM):
    """Standard magnitude of a diffuse reflector of the object's size."""
    length = lengthM or 0
    diameter = diameterM or 0
    body = max(length, diameter)
    span = min(spanM or 0, MAX_SPAN_RATIO * body) if body else (spanM or 0)
    area = length * diameter
    if span > body:
        area += 0.5 * (span - body) * (min(length, diameter) or body)
    if area <= 0:
        return None
    # Lambertian body: reflected fraction (2/3) albedo A / (pi d^2), times
    # the phase function at 90 degrees, 1/pi.
    flux = (2 / 3) * ALBEDO * area / (math.pi * STANDARD_RANGE_M ** 2) / math.pi
    return round(SUN_MAGNITUDE - 2.5 * math.log10(flux), 2)


def brightnessRows(db):
    db.execute(f"ATTACH DATABASE 'file:{ORBITAL_DB_PATH}?mode=ro' AS orbital")
    try:
        found = db.execute(
            'SELECT o.noradID, o.objectType, COALESCE(g.name, o.name), g.bus, COALESCE(g.launchDate, o.launchDate), '
            'g.lengthM, g.diameterM, g.spanM '
            'FROM orbital.orbital_objects o LEFT JOIN gcatObjects g ON g.noradID = o.noradID '
            "WHERE (o.decayDate IS NULL OR o.decayDate = '') AND o.objectType IN ('PAY', 'R/B') "
            'GROUP BY o.noradID').fetchall()
    finally:
        db.execute('DETACH DATABASE orbital')
    rows = []
    for noradID, objectType, name, bus, launchDate, lengthM, diameterM, spanM in found:
        if noradID in STATIONS:
            rows.append((noradID, STATIONS[noradID], 'station'))
            continue
        if (name or '').upper().startswith('STARLINK'):
            classified = starlinkMagnitude(bus, launchDate)
            if classified:
                rows.append((noradID, classified[0], f'starlink {classified[1]}'))
                continue
        magnitude = sizeMagnitude(lengthM, diameterM, spanM)
        rows.append((noradID, magnitude, 'size') if magnitude is not None
                    else (noradID, DEFAULT_MAGNITUDE[objectType], 'default'))
    return rows


def refreshBrightness(db):
    rows = brightnessRows(db)
    with db:
        db.execute('DROP TABLE IF EXISTS gcatBrightness')
        db.execute('CREATE TABLE gcatBrightness (noradID INTEGER PRIMARY KEY, stdMag REAL, source TEXT)')
        db.executemany('INSERT OR REPLACE INTO gcatBrightness VALUES (?, ?, ?)', rows)
    counts = {}
    for _, _, source in rows:
        counts[source] = counts.get(source, 0) + 1
    print(f'  [brightness] {len(rows)} payloads and rocket bodies -> gcatBrightness ({", ".join(f"{k} {v}" for k, v in sorted(counts.items()))})')
    return len(rows)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    connection = sqlite3.connect(DB_PATH, uri=True)
    refreshBrightness(connection)
    connection.close()
