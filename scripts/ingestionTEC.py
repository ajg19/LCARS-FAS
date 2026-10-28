"""Total electron content (TEC) ingestion: keeps databases/ingestionTEC.db holding
two sets of global TEC maps for the SAT COMMS and HF COMMS views
(0_documentation/plans/spaceWeatherChartsPlan.md, sections 8, 9 and 13.5). Fetches
and stores only; the publish step copies the maps into siteWeather.db.

  tecCode     daily (cron 09:15 UTC; see below): CODE, the Center for Orbit Determination in
              Europe at the Astronomical Institute of the University of Bern. Four IONEX files,
              each 25 hourly global maps of vertical TEC:
                COD0OPSRAP_<yyyyddd>0000_01D_01H_GIM.INX.gz  rapid, observed: the previous UTC day
                COD0OPSP0D_...   1-day prediction: today        (product pred1)
                COD0OPSP1D_...   2-day prediction: tomorrow     (product pred2)
                COD0OPSP4D_...   5-day prediction: today + 4    (product pred5)
              The date in a file name is the day the maps COVER (the day of the first map), not the
              day they were issued (verified 24 Oct 2026: P1D_2026298, "2-day predicted maps for day
              298", first map 25 Oct 00:00, issued 24 Oct 08:15). CODE issues all four at about
              08:00 to 08:15 UTC, so a run before 08:30 finds the day's files missing (HTTP 404: noted,
              not a failure). The rapid file of the day before is also tried, if not held (a catch-up).
              A file already held (table sourceFiles) is never fetched again; one GET per file, 2 to 5 s
              apart, no directory listing. The host redirects to a public S3 bucket (urllib follows).
  tecGlotec   every 3 hours: NOAA SWPC GloTEC (US government; credit NOAA SWPC), the newest 2D map
              from the directory listing https://services.swpc.noaa.gov/products/glotec/geojson_2d_urt/
              (the index JSON flaps between empty and full and is not used). Files are named
              glotec_icao_<yyyymmddThhmmss>Z.geojson, every 10 minutes at :x5, about 20 minutes after
              their valid time; 2.4 MB each, not gzipped by the server. A map already held is never
              fetched again. If the listing fails: the name computed from the clock (now - 30 minutes,
              down to a :x5 minute), one step (10 minutes) back on a 404.

Storage:
  tecMaps      one row per map: source ('code' or 'glotec'), product (rapid, pred1, pred2, pred5,
               glotec), kind (observed or prediction; GloTEC is an analysis, so observed), issuedUtc,
               validUtc, and gz: the compact map as gzipped JSON (a few kB for CODE, tens of kB for
               GloTEC; the website serves it as it is). Kept KEEP_DAYS (7) days from the valid time,
               older rows are deleted at the end of each run.
  samples      cheap per-map summaries, kept for good: codeTecMax, codeTecMaxLat, codeTecMaxLon (the
               observed hourly maps) and glotecTecMax, ...Lat, ...Lon: the global maximum TEC and where.
  sourceFiles  the CODE files already fetched (never fetched twice); rows older than 14 days go.

Compact map formats (all JSON, keys sorted):
  CODE    {source, product, kind, issuedUtc, validUtc, latMax 87.5, latStep -2.5, lonMin -180, lonStep 5,
           unit 'tenthsTECU', rows}: rows[i] is latitude latMax + i * latStep (71 rows, 87.5 to -87.5),
           73 integers from longitude -180 to 180 (both ends are the same meridian); null = no value (9999).
  GloTEC  {source, product, kind, issuedUtc, validUtc, latMin -88.75, latStep 2.5, nLat 72, lonMin -177.5,
           lonStep 5, nLon 72, tec, anom, nmf2, hmf2, q}: five flat lists of 5184, index = latRow * 72 +
           lonCol, latitude rows from the south. tec and anom in tenths of a TECU, nmf2 in 1e10 electrons
           per m3, hmf2 in km, q is NOAA's quality_flag (0 to 5; the meaning is not documented in the
           feed). foF2 (MHz) is 8.98 * sqrt(NmF2 / 1e12) = 0.898 * sqrt(nmf2): indicative only.

GloTEC anomaly and quality_flag (Spock, enterpriseCrewOutput/spock_gloTecAnomaly_2026-10-24.md;
source https://spaceweather.gov/products/glotec, fetched 24 Oct 2026):
  CONFIRMED  anomaly = deviation of TEC from its 30-day median. quality_flag = the mean number of
             F-region observations in the cell's vertical profile, rounded up, capped at 5: 0 = no
             observations (the TEC relaxes to IRI-2016 climatology driven by F10.7, so the anomaly is then
             the model's seasonal / F10.7 response, not observed weather; 72% of cells in the saved map),
             5 = dense coverage (14%). The flag measures data coverage, not the size of an error.
  INFERRED   (about 95%) the anomaly is in TECU; the median is per cell at the same time of day over the
             PRECEDING 30 days; the sign is current minus median. NOAA states no unit.
  UNKNOWN    whether the 30 days include today, how "same time" is matched, how gaps are handled.
  The site greys the anomaly out where the flag is 0 (tec-at: observed / anomalyReliable).

Citation (CODE; asked for by AIUB): Dach, R., S. Schaer, D. Arnold, E. Brockmann, M. Kalarus, C. Kobel,
M. Lasser, P. Stebler, A. Jaeggi (2026), CODE rapid product series for the IGS. Astronomical Institute,
University of Bern. DOI 10.48620/97772. Credits are in assets/acknowledgments.html.

Each file is validated whole before anything from it is stored; a surprise rejects that file (nothing
stored) and the run is recorded as failed.
"""

import argparse
import gzip
import json
import math
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from common import USER_AGENT, httpGet
from dbPaths import TEC_DB, dbPath
from ingestionLog import trackRun
from spaceWeatherSamples import FeedError, MAX_GAP_SEC, MIN_GAP_SEC, connect, upsertSamples

CODE_URL = 'https://www.aiub.unibe.ch/download/CODE/'
GLOTEC_URL = 'https://services.swpc.noaa.gov/products/glotec/geojson_2d_urt/'
JOB_CODE, JOB_GLOTEC = 'tecCode', 'tecGlotec'
KEEP_DAYS = 7
SOURCE_FILE_KEEP_DAYS = 14
TIMEOUT_SEC = 60

# file prefix -> (product, kind, days from today to the day the file covers, words the file's comment must hold)
CODE_FILES = {
    'COD0OPSRAP': ('rapid', 'observed', -1, 'RAPID'),
    'COD0OPSP0D': ('pred1', 'prediction', 0, '1-DAY PREDICTED'),
    'COD0OPSP1D': ('pred2', 'prediction', 1, '2-DAY PREDICTED'),
    'COD0OPSP4D': ('pred5', 'prediction', 4, '5-DAY PREDICTED'),
}
CODE_CATCH_UP = ('COD0OPSRAP', -2)     # also tried, if not held

TEC_SQL = '''
    CREATE TABLE IF NOT EXISTS tecMaps (
        source    TEXT NOT NULL,
        product   TEXT NOT NULL,
        issuedUtc TEXT NOT NULL,
        validUtc  TEXT NOT NULL,
        kind      TEXT NOT NULL,
        gz        BLOB NOT NULL,
        PRIMARY KEY (source, product, issuedUtc, validUtc)
    ) WITHOUT ROWID;
    CREATE INDEX IF NOT EXISTS tecMapsByValid ON tecMaps (source, validUtc);
    CREATE TABLE IF NOT EXISTS sourceFiles (
        name      TEXT PRIMARY KEY,
        fetchedAt TEXT NOT NULL
    ) WITHOUT ROWID;
'''

MONTHS = {m: i for i, m in enumerate(('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                                       'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'), 1)}


def openDb(path=None):
    db = connect(path or dbPath(TEC_DB))
    db.executescript(TEC_SQL)
    db.commit()
    return db


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def packMap(record):
    """The record as gzipped JSON (mtime 0, so the same map is the same bytes)."""
    return gzip.compress(json.dumps(record, separators=(',', ':'), sort_keys=True).encode('utf-8'), 9, mtime=0)


def unpackMap(blob):
    return json.loads(gzip.decompress(blob).decode('utf-8'))


# --- Fetching -------------------------------------------------------------------

class Fetcher:
    """Callable fetch(url, binary=False) -> (status, body): the body is bytes if binary, else text. An HTTP
    error status is returned, not raised; redirects are followed (CODE's host hands over to an S3 bucket).
    A random 2 to 5 s is left between two requests, as a person clicking about would. Tests pass their own
    function and never reach this."""

    def __init__(self, sleep=time.sleep):
        self.sleep, self.count = sleep, 0

    def __call__(self, url, binary=False):
        if self.count:
            self.sleep(random.uniform(MIN_GAP_SEC, MAX_GAP_SEC))
        self.count += 1
        if not binary:
            return httpGet(url, {'Accept-Encoding': 'gzip'}, TIMEOUT_SEC)
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, b''


# --- CODE (IONEX) ---------------------------------------------------------------

def codeFileName(prefix, day):
    return f'{prefix}_{day.year}{day.timetuple().tm_yday:03d}0000_01D_01H_GIM.INX.gz'


def ionexTime(parts):
    try:
        year, month, day, hour, minute, second = (int(x) for x in parts)
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        raise FeedError(f'ionex: unreadable epoch {parts!r}')


def parseIonex(text, product, kind, comment):
    """One CODE IONEX 1.0 file -> [(issuedUtc, validUtc, record)] for its TEC maps (the RMS maps and the
    bias block are ignored). Checks the grid is the one expected (71 x 73, 450 km, 0.1 TECU), that the
    comment says what the file name says (`comment`), and that the number of maps is the number declared."""
    lines = text.splitlines()
    header = {}
    end = None
    for number, line in enumerate(lines):
        label = line[60:].strip()
        if label == 'END OF HEADER':
            end = number
            break
        header.setdefault(label, []).append(line[:60])
    if end is None:
        raise FeedError('ionex: no end of header')
    if not header.get('IONEX VERSION / TYPE', [''])[0].split()[:1] == ['1.0']:
        raise FeedError('ionex: not IONEX version 1.0')
    def need(label):
        if label not in header:
            raise FeedError(f'ionex: no {label}')
        return header[label][0].split()

    expected = {'HGT1 / HGT2 / DHGT': ['450.0', '450.0', '0.0'], 'LAT1 / LAT2 / DLAT': ['87.5', '-87.5', '-2.5'],
                'LON1 / LON2 / DLON': ['-180.0', '180.0', '5.0'], 'EXPONENT': ['-1'], 'MAP DIMENSION': ['2']}
    for label, values in expected.items():
        if need(label) != values:
            raise FeedError(f'ionex: {label} is {need(label)}, expected {values}')
    if comment not in ' '.join(header.get('COMMENT', [])).upper():
        raise FeedError(f'ionex: the comment does not say {comment!r}')
    declared = int(need('# OF MAPS IN FILE')[0])
    made = re.search(r'(\d\d)-([A-Z]{3})-(\d\d) (\d\d):(\d\d)', header.get('PGM / RUN BY / DATE', [''])[0])
    if not made or made.group(2) not in MONTHS:
        raise FeedError('ionex: no issue time')
    issued = stamp(datetime(2000 + int(made.group(3)), MONTHS[made.group(2)], int(made.group(1)),
                            int(made.group(4)), int(made.group(5))))
    maps, inside, valid, rows, row = [], False, None, None, None
    for line in lines[end + 1:]:
        label = line[60:].strip()
        if label == 'START OF TEC MAP':
            inside, valid, rows, row = True, None, [], None
        elif label == 'END OF TEC MAP':
            if valid is None or len(rows) != 71:
                raise FeedError(f'ionex: map {valid} has {len(rows or [])} latitude rows')
            maps.append((issued, valid, {
                'source': 'code', 'product': product, 'kind': kind, 'issuedUtc': issued, 'validUtc': valid,
                'latMax': 87.5, 'latStep': -2.5, 'lonMin': -180, 'lonStep': 5, 'unit': 'tenthsTECU', 'rows': rows}))
            inside = False
        elif not inside:
            continue
        elif label == 'EPOCH OF CURRENT MAP':
            valid = stamp(ionexTime(line[:60].split()))
        elif label == 'LAT/LON1/LON2/DLON/H':
            if row is not None and len(row) != 73:
                raise FeedError(f'ionex: latitude row of {len(row)} values')
            expectedLat = 87.5 - 2.5 * len(rows)
            if [float(x) for x in re.findall(r'-?\d+\.\d', line[:60])] != [expectedLat, -180.0, 180.0, 5.0, 450.0]:
                raise FeedError(f'ionex: latitude row {len(rows)} is not {expectedLat}')
            row = []
            rows.append(row)
        elif re.fullmatch(r'[-\d\s]*', label):       # a data line: 16 values of 5 columns fill all 80, so the label columns hold digits
            if row is None:
                raise FeedError('ionex: values before a latitude line')
            for token in line.split():
                if not re.fullmatch(r'-?\d{1,4}', token):
                    raise FeedError(f'ionex: unreadable value {token!r}')
                value = int(token)
                if value != 9999 and not -100 <= value <= 3000:
                    raise FeedError(f'ionex: TEC {value} out of range')
                row.append(None if value == 9999 else value)
        else:
            raise FeedError(f'ionex: unexpected line {label!r} inside a map')
        if label == 'END OF TEC MAP':
            row = None
    for issuedUtc, validUtc, record in maps:
        if any(len(r) != 73 for r in record['rows']):
            raise FeedError(f'ionex: map {validUtc} is not 71 x 73')
    if len(maps) != declared or declared < 2:
        raise FeedError(f'ionex: {len(maps)} maps, {declared} declared')
    if len({m[1] for m in maps}) != len(maps):
        raise FeedError('ionex: a map time is repeated')
    return maps


def tecMaxOfRows(rows, latOf, lonOf):
    """(maximum, lat, lon) of a rows grid (None = no value): among equal maxima the lowest |lat|, then the lowest lon."""
    best = None
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            if v is None:
                continue
            key = (-v, abs(latOf(i)), lonOf(j))
            if best is None or key < best[0]:
                best = (key, v, latOf(i), lonOf(j))
    return best[1:] if best else (None, None, None)


def codeSamples(maps):
    """Peak TEC and where, for the OBSERVED hourly maps only (a prediction would collide with them in time)."""
    rows = []
    for issued, valid, record in maps:
        if record['kind'] != 'observed':
            continue
        top, lat, lon = tecMaxOfRows(record['rows'], lambda i: 87.5 - 2.5 * i, lambda j: -180.0 + 5 * j)
        if top is None:
            continue
        quality = f'{record["product"]} issued {issued}'
        rows += [('codeTecMax', valid, top / 10, 'TECU', quality), ('codeTecMaxLat', valid, lat, 'deg', quality),
                 ('codeTecMaxLon', valid, lon, 'deg', quality)]
    return rows


def storeMaps(db, maps, samples=()):
    """Maps (issuedUtc, validUtc, record) into tecMaps; returns the rows new or changed."""
    changes = 0
    with db:
        for issued, valid, record in maps:
            blob = packMap(record)
            held = db.execute('SELECT gz FROM tecMaps WHERE source = ? AND product = ? AND issuedUtc = ? AND validUtc = ?',
                              (record['source'], record['product'], issued, valid)).fetchone()
            if held and bytes(held[0]) == blob:
                continue
            db.execute('INSERT OR REPLACE INTO tecMaps (source, product, issuedUtc, validUtc, kind, gz) VALUES (?, ?, ?, ?, ?, ?)',
                       (record['source'], record['product'], issued, valid, record['kind'], blob))
            changes += 1
    return changes + upsertSamples(db, list(samples))


def prune(db, now):
    """Deletes maps whose valid time is more than KEEP_DAYS before `now` (a datetime), and old file records."""
    cutoff = stamp((now - timedelta(days=KEEP_DAYS)).replace(minute=0, second=0, microsecond=0))
    with db:
        maps = db.execute('DELETE FROM tecMaps WHERE validUtc < ?', (cutoff,)).rowcount
        db.execute('DELETE FROM sourceFiles WHERE fetchedAt < ?', (stamp(now - timedelta(days=SOURCE_FILE_KEEP_DAYS)),))
    return maps


def runCode(db, fetch=None, now=None):
    """The tecCode job. Returns (changes, failed, note)."""
    fetch, now = fetch or Fetcher(), now or datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()
    wanted = [(prefix, today + timedelta(days=offset)) for prefix, (_, _, offset, _) in CODE_FILES.items()]
    wanted.insert(1, (CODE_CATCH_UP[0], today + timedelta(days=CODE_CATCH_UP[1])))
    held = {r[0] for r in db.execute('SELECT name FROM sourceFiles')}
    changes, notes, failures = 0, [], []
    for prefix, day in wanted:
        name = codeFileName(prefix, day)
        if name in held:
            continue
        product, kind, _, comment = CODE_FILES[prefix]
        try:
            status, body = fetch(CODE_URL + name, True)
            if status == 404:
                notes.append(f'{product} {day} not yet published')
                print(f'  {name}: 404, not yet published')
                continue
            if status >= 400 or not body:
                raise Exception(f'HTTP {status}')
            maps = parseIonex(gzip.decompress(body).decode('ascii', errors='replace'), product, kind, comment)
            changed = storeMaps(db, maps, codeSamples(maps))
            with db:
                db.execute('INSERT OR REPLACE INTO sourceFiles (name, fetchedAt) VALUES (?, ?)', (name, stamp(now)))
            changes += changed
            notes.append(f'{product} {day} {len(maps)} maps')
            print(f'  {name}: {len(maps)} maps, {changed} changed')
        except Exception as error:
            failures.append(f'{name}: {type(error).__name__}: {error}')
            print(f'  {name}: ERROR {error} -- nothing stored from it')
    deleted = prune(db, now)
    changes += deleted
    if deleted:
        notes.append(f'{deleted} old maps deleted')
    note = ', '.join(notes) + ('; FAILED ' + '; '.join(failures) if failures else '')
    return changes, bool(failures), (note or 'all files already held')[:500]


# --- GloTEC ---------------------------------------------------------------------

GLOTEC_LAT0, GLOTEC_LAT_STEP, GLOTEC_LON0, GLOTEC_LON_STEP, GLOTEC_N = -88.75, 2.5, -177.5, 5, 72
GLOTEC_NAME = re.compile(r'glotec_icao_(\d{8}T\d{6}Z)\.geojson')


def glotecValid(stampText):
    """'20261024T184500Z' -> '2026-10-24T18:45:00Z'."""
    return stamp(datetime.strptime(stampText, '%Y%m%dT%H%M%SZ'))


def glotecName(moment):
    return f'glotec_icao_{moment:%Y%m%dT%H%M00Z}.geojson'


def newestInListing(html):
    """The newest map's valid time (UTC text) named in the directory listing; FeedError if there is none."""
    found = GLOTEC_NAME.findall(html)
    if not found:
        raise FeedError('glotec: no map named in the listing')
    return glotecValid(max(found))


def computedValid(now, back=0):
    """The valid time to expect without a listing: now - 30 minutes, down to a :x5 minute, `back` steps of 10 minutes earlier."""
    t = (now - timedelta(minutes=30)).replace(second=0, microsecond=0)
    t -= timedelta(minutes=(t.minute % 10 - 5) % 10)
    return stamp(t - timedelta(minutes=10 * back))


def numOrNone(value, what, scale):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FeedError(f'glotec: {what} is {value!r}')
    return round(value * scale)


def parseGlotec(text):
    """One GloTEC GeoJSON map -> (record, samples). The map must hold every cell of the 72 x 72 grid
    (longitude -177.5 to 177.5 by 5, latitude -88.75 to 88.75 by 2.5) exactly once."""
    try:
        data = json.loads(text)
    except ValueError as error:
        raise FeedError(f'glotec: not JSON: {error}')
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
        raise FeedError('glotec: expected a FeatureCollection')
    try:
        valid = stamp(datetime.strptime(data['time_tag'], '%Y-%m-%dT%H:%M:%SZ'))
    except (KeyError, TypeError, ValueError):
        raise FeedError('glotec: no time_tag')
    cells = GLOTEC_N * GLOTEC_N
    fields = {'tec': [None] * cells, 'anom': [None] * cells, 'nmf2': [None] * cells, 'hmf2': [None] * cells, 'q': [None] * cells}
    seen = set()
    for feature in data['features']:
        try:
            lon, lat = feature['geometry']['coordinates']
            props = feature['properties']
            column, line = (lon - GLOTEC_LON0) / GLOTEC_LON_STEP, (lat - GLOTEC_LAT0) / GLOTEC_LAT_STEP
            if feature['geometry']['type'] != 'Point' or column != int(column) or line != int(line) \
                    or not (0 <= column < GLOTEC_N and 0 <= line < GLOTEC_N):
                raise ValueError
            index = int(line) * GLOTEC_N + int(column)
            if index in seen:
                raise FeedError(f'glotec: cell {lon},{lat} twice')
            seen.add(index)
            fields['tec'][index] = numOrNone(props['tec'], 'tec', 10)
            fields['anom'][index] = numOrNone(props['anomaly'], 'anomaly', 10)
            fields['nmf2'][index] = numOrNone(props['NmF2'], 'NmF2', 1e-10)
            fields['hmf2'][index] = numOrNone(props['hmF2'], 'hmF2', 1)
            flag = props['quality_flag']
            if flag is not None and (isinstance(flag, bool) or not isinstance(flag, int)):
                raise FeedError(f'glotec: quality_flag {flag!r}')
            fields['q'][index] = flag
        except FeedError:
            raise
        except (KeyError, TypeError, ValueError):
            raise FeedError(f'glotec: unexpected feature {str(feature)[:80]}')
    if len(seen) != cells:
        raise FeedError(f'glotec: {len(seen)} cells of {cells}')
    if all(v is None for v in fields['tec']):
        raise FeedError('glotec: no TEC value at all')
    record = {'source': 'glotec', 'product': 'glotec', 'kind': 'observed', 'issuedUtc': valid, 'validUtc': valid,
              'latMin': GLOTEC_LAT0, 'latStep': GLOTEC_LAT_STEP, 'nLat': GLOTEC_N,
              'lonMin': GLOTEC_LON0, 'lonStep': GLOTEC_LON_STEP, 'nLon': GLOTEC_N, **fields}
    best = max((i for i in range(cells) if fields['tec'][i] is not None),
               key=lambda i: (fields['tec'][i], -abs(GLOTEC_LAT0 + GLOTEC_LAT_STEP * (i // GLOTEC_N)), -(i % GLOTEC_N)))
    quality = 'GloTEC'
    samples = [('glotecTecMax', valid, fields['tec'][best] / 10, 'TECU', quality),
               ('glotecTecMaxLat', valid, GLOTEC_LAT0 + GLOTEC_LAT_STEP * (best // GLOTEC_N), 'deg', quality),
               ('glotecTecMaxLon', valid, GLOTEC_LON0 + GLOTEC_LON_STEP * (best % GLOTEC_N), 'deg', quality)]
    return record, samples


def fetchLatestGlotec(fetch, now, isHeld):
    """The newest GloTEC map not already held: (record, samples), or None when the newest is held. `fetch` is
    fetch(url) -> (status, text); `isHeld(validUtc)` says whether a map is held. The directory listing is
    used; if it fails, the name is computed from the clock and one step back is tried on a 404. At most one
    listing and one map are fetched. Raises on any other failure."""
    candidates = []
    try:
        status, html = fetch(GLOTEC_URL)
        if status != 200:
            raise Exception(f'HTTP {status}')
        candidates = [newestInListing(html)]
    except Exception as error:
        print(f'  listing failed ({error}); using the computed name')
        candidates = [computedValid(now), computedValid(now, 1)]
    for number, valid in enumerate(candidates):
        if isHeld(valid):
            print(f'  {valid} already held; nothing fetched')
            return None
        status, text = fetch(GLOTEC_URL + glotecName(datetime.strptime(valid, '%Y-%m-%dT%H:%M:%SZ')))
        if status == 404 and number + 1 < len(candidates):
            continue
        if status != 200:
            raise Exception(f'HTTP {status}')
        record, samples = parseGlotec(text)
        if record['validUtc'] != valid:
            raise FeedError(f'glotec: asked for {valid}, the map says {record["validUtc"]}')
        return record, samples
    return None


def runGlotec(db, fetch=None, now=None):
    """The tecGlotec job. Returns (changes, failed, note)."""
    fetch, now = fetch or Fetcher(), now or datetime.now(timezone.utc).replace(tzinfo=None)
    held = lambda valid: db.execute("SELECT 1 FROM tecMaps WHERE source = 'glotec' AND validUtc = ?", (valid,)).fetchone() is not None   # noqa: E731
    try:
        found = fetchLatestGlotec(fetch, now, held)
        changes, note = 0, 'newest map already held'
        if found:
            record, samples = found
            changes = storeMaps(db, [(record['issuedUtc'], record['validUtc'], record)], samples)
            note = f'map {record["validUtc"]}, peak {samples[0][2]} TECU'
    except Exception as error:
        print(f'  ERROR {error} -- nothing stored')
        return 0, True, f'{type(error).__name__}: {error}'[:500]
    deleted = prune(db, now)
    print(f'  {note}; {deleted} old maps deleted')
    return changes + deleted, False, note + (f'; {deleted} old maps deleted' if deleted else '')


def main(argv=None):
    parser = argparse.ArgumentParser(description='TEC maps ingestion (CODE, NOAA GloTEC)')
    parser.add_argument('--job', choices=(JOB_CODE, JOB_GLOTEC), required=True)
    args = parser.parse_args(argv)
    db = openDb()
    print(f'\n=== [{time.strftime("%H:%M:%S")}] TEC ingestion ({args.job}) ===')
    with trackRun(db, args.job) as run:
        run.changes, run.failed, run.note = (runCode if args.job == JOB_CODE else runGlotec)(db)
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} changes')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
