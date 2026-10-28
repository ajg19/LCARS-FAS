"""Builds databases/ingestionGeoIP.db, the lookup that scripts/visitCounter.py uses
to turn a visitor's address into a city, from a DB-IP "City Lite" CSV file.

    python 0_tools/buildGeoIPDb.py path/to/dbip-city-lite-YYYY-MM.csv[.gz]
    python 0_tools/buildGeoIPDb.py FILE --dry-run     # show how the first rows parse; write nothing

YOU download the file (about 100 MB or more compressed) yourself, from
https://db-ip.com/db/download/ip-to-city-lite, once a month at most: this script
makes no network requests. Expected columns, without a header row:
    start address, end address, continent, country, state or province, city, latitude, longitude
(a header row is skipped; check the --dry-run output the first time, as the
column order is from memory). Rows without a position are skipped; rows without
a city are kept under the city name "Unknown city" at the country position DB-IP
gives. Adjacent ranges in the same place are merged, which shrinks the file.

The file is built beside the database and swapped in whole. Like the ground-segment
database it is built here on the laptop and uploaded; it is not committed.
LICENCE: DB-IP City Lite is CC BY 4.0, so the site must credit "IP Geolocation by
DB-IP" (add it to ABOUT > CREDITS before the visit counter goes live).
"""

import csv
import gzip
import ipaddress
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import dbPaths  # noqa: E402


def openCsv(path):
    return gzip.open(path, 'rt', encoding='utf-8', newline='') if path.endswith('.gz') else open(path, encoding='utf-8', newline='')


def parseRow(row):
    """(version, start int, end int, (city, country, latitude, longitude)), or None for a header or unusable row."""
    if len(row) < 8:
        return None
    try:
        start, end = ipaddress.ip_address(row[0].strip()), ipaddress.ip_address(row[1].strip())
        latitude, longitude = round(float(row[6]), 2), round(float(row[7]), 2)
    except ValueError:
        return None
    if start.version != end.version:
        return None
    city = row[5].strip() or 'Unknown city'
    return start.version, int(start), int(end), (city, row[3].strip() or '??', latitude, longitude)


def buildGeoIP(csvPath, outPath):
    """Writes the lookup database; returns (ranges4, ranges6, places)."""
    temporary = outPath + '.new'
    if os.path.exists(temporary):
        os.remove(temporary)
    conn = sqlite3.connect(temporary)
    conn.executescript('''
        CREATE TABLE places (placeID INTEGER PRIMARY KEY, city TEXT NOT NULL, country TEXT NOT NULL,
                             latitude REAL NOT NULL, longitude REAL NOT NULL);
        CREATE TABLE ipRanges4 (startIP INTEGER PRIMARY KEY, endIP INTEGER NOT NULL, placeID INTEGER NOT NULL);
        CREATE TABLE ipRanges6 (startIP BLOB PRIMARY KEY, endIP BLOB NOT NULL, placeID INTEGER NOT NULL) WITHOUT ROWID;
    ''')
    placeIDs = {}
    pending = {4: None, 6: None}   # per version: [start, end, placeID] not yet written
    counts = {4: 0, 6: 0}

    def flush(version):
        item = pending[version]
        if item is None:
            return
        start, end, placeID = item
        if version == 4:
            conn.execute('INSERT INTO ipRanges4 VALUES (?, ?, ?)', (start, end, placeID))
        else:
            conn.execute('INSERT INTO ipRanges6 VALUES (?, ?, ?)', (start.to_bytes(16, 'big'), end.to_bytes(16, 'big'), placeID))
        counts[version] += 1
        pending[version] = None

    with openCsv(csvPath) as handle:
        for row in csv.reader(handle):
            parsed = parseRow(row)
            if parsed is None:
                continue
            version, start, end, place = parsed
            if place not in placeIDs:
                placeIDs[place] = len(placeIDs) + 1
                conn.execute('INSERT INTO places VALUES (?, ?, ?, ?, ?)', (placeIDs[place], *place))
            placeID = placeIDs[place]
            item = pending[version]
            if item is not None and item[2] == placeID and item[1] + 1 == start:
                item[1] = end   # adjacent and in the same place: extend
            else:
                flush(version)
                pending[version] = [start, end, placeID]
    flush(4)
    flush(6)
    conn.commit()
    conn.close()
    os.replace(temporary, outPath)
    return counts[4], counts[6], len(placeIDs)


def main(argv):
    if not argv or argv[0].startswith('-'):
        sys.exit(__doc__)
    csvPath = argv[0]
    if '--dry-run' in argv:
        with openCsv(csvPath) as handle:
            for number, row in enumerate(csv.reader(handle)):
                print(row, '->', parseRow(row))
                if number >= 7:
                    break
        return
    outPath = dbPaths.dbPath(dbPaths.GEOIP_DB)
    ranges4, ranges6, places = buildGeoIP(csvPath, outPath)
    print(f'Wrote {outPath}: {ranges4:,} IPv4 ranges, {ranges6:,} IPv6 ranges, {places:,} places, '
          f'{os.path.getsize(outPath) / 1e6:.1f} MB')


if __name__ == '__main__':
    main(sys.argv[1:])
