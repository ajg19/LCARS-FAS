"""Builds databases/skyCatalogue.db: the fixed sky behind GRD VIEW's sky
view -- the stars, star names, constellations, the Milky Way and the bright
deep-sky objects.

Static data, not a scheduled job: run it once (locally and once on the
server), and again only if what is kept here changes. The Moon, planets and
Sun are not stored -- they are calculated in the browser with Astronomy
Engine (assets/astronomy/) -- and satellites come from the existing
orbital-object pipeline.

Source: the data files of d3-celestial by Olaf Frohn (BSD licence;
github.com/ofrohn/d3-celestial), pinned to one commit so a rebuild gives the
same result. Their own sources:
    stars, star names   XHIP: An Extended Hipparcos Compilation
                        (Anderson & Francis 2012), with name cross-indexes
    constellations      IAU constellation lines and names
    Milky Way           Milky Way Outline Catalog (Jose R. Vieira)
    deep-sky objects    d3-celestial's hand-picked bright list (from the
                        Saguaro Astronomy Club database), names from
                        dsonames.json
All positions are J2000. d3-celestial stores right ascension as a GeoJSON
longitude, -180..180 degrees; it is converted back to 0..360 here.

Tables (degrees throughout):
    skyStars                 hip, raDeg, decDeg, mag, bv, name, desig
                             -- 5,000-odd stars to magnitude 6 (naked eye);
                             name (proper name) and desig (e.g. 'α Lyr')
                             where the star has them
    skyConstellations        desig, name, labelRaDeg, labelDecDeg, rank --
                             one row per label: Serpens, the one constellation
                             in two parts, has two (Serpens Caput and Cauda,
                             both 'Ser')
    skyConstellationLines    desig, lineIndex, pointsJson -- each line a
                             JSON array of [raDeg, decDeg] points
    skyMilkyWay              level, ringIndex, pointsJson -- outline rings,
                             level 1 (faintest) to 5 (brightest). Each level
                             is one polygon: ring 0 its outline, the rest
                             holes. Simplified to MILKY_WAY_TOLERANCE_DEG
                             (about 30,000 points down to a few thousand).
    skyDeepSky               id, name, type, raDeg, decDeg, mag, dimArcmin --
                             the naked-eye clusters, nebulae and galaxies;
                             type as d3-celestial: oc open cluster, gc
                             globular, s/sd/i galaxy, en/sfr nebula
    skyBuild                 source, sourceCommit, builtAt
Each run replaces every table inside one transaction.
"""

import json
import sqlite3
import sys
import urllib.request

from dbPaths import SKY_DB, dbPath
DB_PATH = dbPath(SKY_DB)

D3C_COMMIT = '7e720a3de062059d4c5400a379146a601d9010e0'   # d3-celestial master, 2022-07-05
D3C_DATA_URL = f'https://raw.githubusercontent.com/ofrohn/d3-celestial/{D3C_COMMIT}/data/'
USER_AGENT = 'LCARS-FAS/1.0 (sky catalogue build; +https://github.com/ajg19/LCARS-FAS)'
HTTP_TIMEOUT_SEC = 120
MILKY_WAY_TOLERANCE_DEG = 0.1   # well below what a 100-degree view can show

TABLES = {
    'skyStars': 'hip INTEGER PRIMARY KEY, raDeg REAL, decDeg REAL, mag REAL, bv REAL, name TEXT, desig TEXT',
    'skyConstellations': 'desig TEXT, name TEXT, labelRaDeg REAL, labelDecDeg REAL, rank INTEGER, PRIMARY KEY (desig, name)',
    'skyConstellationLines': 'desig TEXT, lineIndex INTEGER, pointsJson TEXT, PRIMARY KEY (desig, lineIndex)',
    'skyMilkyWay': 'level INTEGER, ringIndex INTEGER, pointsJson TEXT, PRIMARY KEY (level, ringIndex)',
    'skyDeepSky': 'id TEXT PRIMARY KEY, name TEXT, type TEXT, raDeg REAL, decDeg REAL, mag REAL, dimArcmin REAL',
    'skyBuild': 'source TEXT, sourceCommit TEXT, builtAt TEXT',
}


def fetchJson(name):
    request = urllib.request.Request(D3C_DATA_URL + name, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SEC) as response:
        return json.load(response)


def raDeg(lon):
    """GeoJSON longitude (-180..180) back to right ascension (0..360)."""
    return round(lon % 360, 4)


def point(lonLat):
    return [raDeg(lonLat[0]), round(lonLat[1], 4)]


def nullable(value):
    return value if value not in ('', None) else None


def starRows(stars, names):
    rows = []
    for feature in stars['features']:
        hip = int(feature['id'])
        lon, lat = feature['geometry']['coordinates']
        props = feature['properties']
        bv = props.get('bv')
        named = names.get(str(hip), {})
        rows.append((hip, raDeg(lon), round(lat, 4), float(props['mag']),
                     float(bv) if nullable(bv) is not None else None,
                     nullable(named.get('name')), nullable(named.get('desig'))))
    return rows


def constellationRows(constellations):
    rows = []
    for feature in constellations['features']:
        props = feature['properties']
        lon, lat = feature['geometry']['coordinates']
        rows.append((feature['id'], props['name'], raDeg(lon), round(lat, 4), int(props.get('rank') or 0)))
    return rows


def constellationLineRows(lines):
    # Numbered per constellation across all its features -- Serpens has two.
    rows = []
    nextIndex = {}
    for feature in lines['features']:
        for line in feature['geometry']['coordinates']:
            index = nextIndex.get(feature['id'], 0)
            nextIndex[feature['id']] = index + 1
            rows.append((feature['id'], index, json.dumps([point(p) for p in line], separators=(',', ':'))))
    return rows


def simplify(points, tolerance):
    """Ramer-Douglas-Peucker on [lon, lat] points (planar, in degrees --
    fine at this tolerance away from the poles)."""
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0], points[-1]
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    best, bestIndex = 0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = abs(dx * (py - y1) - dy * (px - x1)) / length if length else ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
        if d > best:
            best, bestIndex = d, i
    if best <= tolerance:
        return [points[0], points[-1]]
    return simplify(points[:bestIndex + 1], tolerance)[:-1] + simplify(points[bestIndex:], tolerance)


def milkyWayRows(milkyWay):
    rows = []
    for feature in milkyWay['features']:
        level = int(feature['id'].replace('ol', ''))   # 'ol1' .. 'ol5'
        rings = [ring for polygon in feature['geometry']['coordinates'] for ring in polygon]
        for index, ring in enumerate(rings):
            # Split at the middle so a closed ring's identical ends don't
            # collapse it, then simplify each half.
            middle = len(ring) // 2
            simple = simplify(ring[:middle + 1], MILKY_WAY_TOLERANCE_DEG)[:-1] + simplify(ring[middle:], MILKY_WAY_TOLERANCE_DEG)
            if len(simple) >= 4:
                rows.append((level, index, json.dumps([point(p) for p in simple], separators=(',', ':'))))
    return rows


def deepSkyRows(deepSky, names):
    rows = []
    for feature in deepSky['features']:
        props = feature['properties']
        if props['type'] == 'pos':   # a position marker (the Galactic Centre), not an object
            continue
        lon, lat = feature['geometry']['coordinates']
        named = (names.get(feature['id']) or {}).get('name')
        dim = str(props.get('dim') or '').split('x')[0]
        rows.append((feature['id'], nullable(named), props['type'], raDeg(lon), round(lat, 4),
                     float(props['mag']), float(dim) if dim else None))
    return rows


def buildSkyCatalogue(db):
    print(f'  fetching d3-celestial data at {D3C_COMMIT[:7]} ...')
    stars = fetchJson('stars.6.json')
    names = fetchJson('starnames.json')
    constellations = fetchJson('constellations.json')
    lines = fetchJson('constellations.lines.json')
    milkyWay = fetchJson('mw.json')
    deepSky = fetchJson('dsos.bright.json')
    deepSkyNames = fetchJson('dsonames.json')

    content = {
        'skyStars': starRows(stars, names),
        'skyConstellations': constellationRows(constellations),
        'skyConstellationLines': constellationLineRows(lines),
        'skyMilkyWay': milkyWayRows(milkyWay),
        'skyDeepSky': deepSkyRows(deepSky, deepSkyNames),
    }
    with db:
        for table, columns in TABLES.items():
            db.execute(f'DROP TABLE IF EXISTS {table}')
            db.execute(f'CREATE TABLE {table} ({columns})')
        for table, rows in content.items():
            placeholders = ', '.join('?' * len(rows[0]))
            db.executemany(f'INSERT INTO {table} VALUES ({placeholders})', rows)
            print(f'  {table}: {len(rows)} rows')
        db.execute("INSERT INTO skyBuild VALUES ('d3-celestial (github.com/ofrohn/d3-celestial)', ?, "
                   "strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))", (D3C_COMMIT,))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    db = sqlite3.connect(DB_PATH)
    buildSkyCatalogue(db)
    db.execute('VACUUM')
    db.close()
    print(f'Sky catalogue written to {DB_PATH}')
