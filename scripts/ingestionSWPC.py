"""NOAA SWPC ingestion: keeps databases/ingestionSWPC.db holding the Space
Weather Prediction Center's real-time products (services.swpc.noaa.gov;
US government, public domain; credit NOAA SWPC).

Step 3 of 0_documentation/plans/spaceWeatherIngestionPlan.md. Fetches and
stores only; the publish step decides what reaches the website. Four jobs,
the same script (--job):

  swpcFast  every 15 min, small files:
              NOAA scales (current, previous day, 3-day probabilities),
              1-minute estimated Kp, GOES protons and X-ray (6-hour files),
              hemispheric power.
  swpcMaps  hourly, separate from swpcSlow so that job is unchanged:
              the OVATION aurora grid (the full global map, both
              hemispheres; per hemisphere the maximum, where it is and the
              equatorward edge of the oval) and the D-RAP absorption table
              (the global map; the maximum and where it is). Nothing is
              specific to one place: a value at any latitude and longitude
              is a lookup in the stored map. GloTEC is NOT built: see the plan.
  swpcPrune daily: deletes the 1-minute rows (L1 field and plasma, GOES
              X-ray) older than LIVE_DAYS (90) days. Fetches nothing.
  swpcSlow  hourly:
              L1 magnetic field and plasma (24 h, 1 minute), F10.7, the
              45-day ap and F10.7 forecast, the 7-day flare list, solar
              radio flux and edited events, Kp (observed, estimated and
              predicted), the Dst copy, the 3-day forecast and 27-day
              outlook (both text).

Not built yet: GloTEC (its index was an empty list on 2026-10-24, so no
real fixture).

Storage (spaceWeatherSamples.py): numeric series go to `samples`; records
that are not one number go to `events`. Judgement calls:
  * 3-day forecast and 27-day outlook: the numbers in the tables become
    samples (forecast Kp, storm probabilities, F10.7, Ap) and the whole
    text goes to `events` ('forecast3day', 'outlook27day', one per issue)
    for the rationale paragraphs.
  * Flares, radio events, radio flux readings: events, the source's record
    as JSON.
  * Quality column: the source (L1: spacecraft; GOES: satellite), the
    reporting schedule (F10.7), observed/estimated/predicted (Kp) or the
    issue date of a forecast.

Quirks handled (Spock's report, section 11):
  * L1 files interleave IMAP, SOLAR1 and ACE; only rows flagged active
    are kept, never averaged across sources. A minute with no active
    row is a gap, not a row (8% and 27% of minutes in a day).
  * The GOES X-ray file interleaves two channels (0.1-0.8 nm is the flare
    class channel); its key is spelt `electron_contaminaton` (the correct
    spelling is accepted too, should NOAA fix it).
  * The GOES proton file interleaves eight energy thresholds.
  * F10.7: three readings a day; the 20:00 UTC 'Noon' one is the daily
    value and the only one with the 90-day mean.

Each feed is validated whole before anything from it is stored; a surprise
rejects that feed (nothing stored) and the run is recorded as failed. The
feeds are independent of each other.
"""

import argparse
import math
import re
import statistics
import sys
import time
from datetime import datetime, timedelta

from dbPaths import SWPC_DB, dbPath
from ingestionLog import trackRun
from spaceWeatherSamples import (FeedError, PacedFetcher, connect, loadJson, number, pruneOldOneMinute, storeFeed,
                                 utcText)

BASE_URL = 'https://services.swpc.noaa.gov/'
JOB_FAST = 'swpcFast'
JOB_SLOW = 'swpcSlow'
JOB_MAPS = 'swpcMaps'
JOB_PRUNE = 'swpcPrune'   # no feeds, so not in JOBS

MONTHS = {m: i for i, m in enumerate(('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}


def openDb(path=None):
    return connect(path or dbPath(SWPC_DB))


# --- Parsing helpers ------------------------------------------------------------

def recordList(data, what, nonEmpty=True):
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise FeedError(f'{what}: expected a list of objects')
    if nonEmpty and not data:
        raise FeedError(f'{what}: empty list')
    return data


def need(record, keys, what):
    missing = [k for k in keys if k not in record]
    if missing:
        raise FeedError(f'{what}: missing {", ".join(missing)}')


def sample(series, tsUtc, value, unit, quality=None):
    return (series, tsUtc, value, unit, quality)


# --- swpcFast feeds -------------------------------------------------------------

def parseScales(text):
    """noaa-scales.json: keys '-1' (yesterday) and '0' (now) hold the
    observed R, S and G scales; '1' to '3' the forecast probabilities and
    the forecast G scale for the next three days."""
    data = loadJson(text)
    if not isinstance(data, dict) or not {'-1', '0', '1', '2', '3'} <= set(data):
        raise FeedError('scales: expected keys -1, 0, 1, 2, 3')
    rows = []
    for key, entry in data.items():
        if key not in ('-1', '0', '1', '2', '3'):
            continue
        what = f'scales[{key}]'
        if not isinstance(entry, dict):
            raise FeedError(f'{what}: expected an object')
        need(entry, ('DateStamp', 'TimeStamp', 'R', 'S', 'G'), what)
        r, s, g = entry['R'], entry['S'], entry['G']
        if not all(isinstance(x, dict) for x in (r, s, g)):
            raise FeedError(f'{what}: R, S and G must be objects')
        if key in ('-1', '0'):
            ts = utcText(f'{entry["DateStamp"]}T{entry["TimeStamp"]}')
            for name, part in (('R', r), ('S', s), ('G', g)):
                need(part, ('Scale',), f'{what}.{name}')
                rows.append(sample(f'noaaScale{name}', ts, number(part['Scale'], what, True), 'scale'))
        else:
            ts = utcText(entry['DateStamp'])
            need(r, ('MinorProb', 'MajorProb'), f'{what}.R')
            need(s, ('Prob',), f'{what}.S')
            need(g, ('Scale',), f'{what}.G')
            rows += [sample('noaaForecastRMinorProb', ts, number(r['MinorProb'], what, True), '%', 'forecast'),
                     sample('noaaForecastRMajorProb', ts, number(r['MajorProb'], what, True), '%', 'forecast'),
                     sample('noaaForecastSProb', ts, number(s['Prob'], what, True), '%', 'forecast'),
                     sample('noaaForecastG', ts, number(g['Scale'], what, True), 'scale', 'forecast')]
    return rows, []


def parseKp1m(text):
    rows = []
    for r in recordList(loadJson(text), 'kp1m'):
        need(r, ('time_tag', 'estimated_kp'), 'kp1m')
        rows.append(sample('swpcKp1m', utcText(r['time_tag']), number(r['estimated_kp'], 'kp1m'), 'Kp'))
    return rows, []


def parseProtons(text):
    """Eight integral energy thresholds interleaved ('>=10 MeV')."""
    rows = []
    for r in recordList(loadJson(text), 'protons'):
        need(r, ('time_tag', 'satellite', 'flux', 'energy'), 'protons')
        found = re.fullmatch(r'>=(\d+) MeV', str(r['energy']))
        if not found:
            raise FeedError(f'protons: unexpected energy {r["energy"]!r}')
        rows.append(sample(f'goesProtonGE{found.group(1)}MeV', utcText(r['time_tag']), number(r['flux'], 'protons'),
                           'pfu', f'GOES-{r["satellite"]}'))
    return rows, []


XRAY_FLOOR = 1.0000001e-9   # 1e-9 stored as float32 reads back as 9.99999972e-10
XRAY_CHANNELS = {'0.1-0.8nm': 'goesXrayLong', '0.05-0.4nm': 'goesXrayShort'}


def parseXray(text):
    """Two channels interleaved. `flux` is the electron-corrected flux; a
    short-channel reading may be flagged as contaminated by electrons."""
    rows = []
    for r in recordList(loadJson(text), 'xray'):
        need(r, ('time_tag', 'satellite', 'flux', 'energy'), 'xray')
        key = next((k for k in ('electron_contaminaton', 'electron_contamination') if k in r), None)
        if key is None:
            raise FeedError('xray: missing electron_contaminaton')
        if r['energy'] not in XRAY_CHANNELS:
            raise FeedError(f'xray: unexpected channel {r["energy"]!r}')
        flux = number(r['flux'], 'xray')
        quality = f'GOES-{r["satellite"]}' + (' contaminated' if r[key] else '')
        if flux is not None and flux <= XRAY_FLOOR:
            quality += ' floor'      # the processing floor max(1e-9, observed - electron correction): an upper limit, not a measurement
        rows.append(sample(XRAY_CHANNELS[r['energy']], utcText(r['time_tag']), flux, 'W/m2', quality))
    return rows, []


def parseHemiPower(text):
    """Text table: observation time, forecast time, north and south power
    in GW; 'n/a' for missing."""
    lines = text.splitlines()
    if not lines or 'Hemispheric Power' not in lines[0]:
        raise FeedError('hemispheric power: unexpected header')
    rows = []
    for line in lines:
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 4:
            raise FeedError(f'hemispheric power: unexpected line {line!r}')
        ts = utcText(parts[0])
        rows.append(sample('hemiPowerNorth', ts, powerValue(parts[2]), 'GW'))
        rows.append(sample('hemiPowerSouth', ts, powerValue(parts[3]), 'GW'))
    if not rows:
        raise FeedError('hemispheric power: no data lines')
    return rows, []


def powerValue(token):
    if token == 'n/a':
        return None
    if not re.fullmatch(r'\d+(\.\d+)?', token):
        raise FeedError(f'hemispheric power: unexpected value {token!r}')
    return float(token)


# --- swpcMaps feeds -------------------------------------------------------------
# Location-free summaries as samples, plus the newest FULL global map in
# latestMaps, integer-coded (plan section 4). A forecast for any place is a
# lookup in that map (server.py, /api/weather/aurora-at).

# The oval's equatorward edge (Spock's definition, 24 Oct 2026): the most equatorward reach of the
# aurora index at or above OVAL_T, scanning from the equator towards the pole, two cells running, in
# the latitudes OVAL_LAT_MIN to OVAL_LAT_TOP only (rows +-89 and +-90 are gridding artefacts and never used),
# smoothed over OVAL_SMOOTH longitudes by their median (a longitude with no edge counts as infinitely
# far poleward), and only if at least OVAL_MIN_LONS longitudes have one. Two tiers (Spock, 24 Oct 2026): T = 10
# is the naked-eye limit (about 1.1 erg cm-2 s-1, 1 kR at 557.7 nm); T = 5 is 'faint, camera only' (about half that).
# MIN_LONS was 30 and is 10: 30 suppressed real, narrow patches near midnight.
OVAL_T, OVAL_T_FAINT = 10, 5
OVAL_RUN, OVAL_LAT_MIN, OVAL_LAT_TOP, OVAL_SMOOTH, OVAL_MIN_LONS = 2, 30, 88, 5, 10


def lonWest180(lon):
    """0..359 east -> -180..179."""
    return lon - 360 if lon > 179 else lon


def ovalEdges(rows, sign, threshold=OVAL_T):
    """rows[i] is latitude -90 + i, 360 integers from longitude 0 east; sign +1 north, -1 south.
    -> (sm, reach, reachLon, cover): sm has 360 values (degrees of latitude magnitude, or None);
    reach is the smallest of them (None if fewer than OVAL_MIN_LONS longitudes have one), reachLon the centre
    (-180..179) of the longest wrapping run of longitudes at the reach, cover the number of longitudes."""
    def value(lat, lon):
        return rows[lat + 90][lon]
    edge = []
    for lon in range(360):
        found = None
        for a in range(OVAL_LAT_MIN, OVAL_LAT_TOP):
            if all(value(sign * (a + k), lon) >= threshold for k in range(OVAL_RUN)):
                found = a
                break
        edge.append(found)
    half, far = OVAL_SMOOTH // 2, float('inf')
    sm = []
    for lon in range(360):
        window = sorted(far if edge[(lon + k) % 360] is None else edge[(lon + k) % 360] for k in range(-half, half + 1))
        sm.append(None if window[half] == far else window[half])
    cover = sum(1 for x in sm if x is not None)
    if cover < OVAL_MIN_LONS:
        return sm, None, None, cover
    reach = min(x for x in sm if x is not None)
    at = [x == reach for x in sm]
    if all(at):
        begin, length = 0, 360
    else:
        first = at.index(False)        # start the scan on a longitude that is not at the reach, so a run never wraps the scan
        begin, length, run = 0, 0, None
        for i in range(1, 361):
            lon = (first + i) % 360
            if at[lon]:
                run = (lon, 1) if run is None else (run[0], run[1] + 1)
                if run[1] > length:
                    begin, length = run
            else:
                run = None
    return sm, float(reach), float(lonWest180((begin + length // 2) % 360)), cover


def parseOvation(text):
    """ovation_aurora_latest.json: 'coordinates' holds [lon 0-359, lat -90..90,
    aurora 0-100] for the whole 360x181 grid, with 'Observation Time' and
    'Forecast Time'. The value is an intensity index ("aurora index", never a
    percentage). Every cell must be present. The map predicts the aurora at the
    FORECAST time, so every sample is stamped with it and the observation time is
    in the quality text ('observed <time>'). Samples, for each hemisphere N and S:
    ovationMax<N|S> (the highest index), ...Lat and ...Lon (where; degrees, lon -180..179;
    among equal maxima the lowest |lat|, then the lowest longitude) and
    ovationEdge<N|S>, ...EdgeLon, ...EdgeCover (see ovalEdges; edge and its longitude are
    missing when the oval is below the threshold at fewer than OVAL_MIN_LONS longitudes), and the same
    with ...Faint (threshold 5, 'faint, camera only'): ovationEdge<N|S>Faint, ...FaintLon, ...FaintCover.
    When no edge exists the site says 'No visible aurora expected; the oval peaks at index M near L
    degrees', from ovationMax<N|S> and its Lat and Lon.
    Map ovation: {obs, forecast, latMin -90, lonMin 0, step 1, rows, edgeN, edgeS}: rows[i] is
    latitude latMin + i, 360 integers from longitude 0 east; edgeN and edgeS are the 360
    smoothed edge latitudes (magnitudes, null where none) for drawing and lookups, and edgeFaintN and
    edgeFaintS the same for the faint tier."""
    data = loadJson(text)
    if not isinstance(data, dict):
        raise FeedError('ovation: expected an object')
    need(data, ('Observation Time', 'Forecast Time', 'coordinates'), 'ovation')
    obs, forecast = utcText(data['Observation Time']), utcText(data['Forecast Time'])
    if not isinstance(data['coordinates'], list):
        raise FeedError('ovation: coordinates is not a list')
    grid = {}
    for cell in data['coordinates']:
        if not (isinstance(cell, list) and len(cell) == 3):
            raise FeedError('ovation: expected [lon, lat, value] cells')
        lon, lat, value = cell
        if not (isinstance(lon, int) and isinstance(lat, int) and 0 <= lon <= 359 and -90 <= lat <= 90):
            raise FeedError(f'ovation: unexpected cell {cell!r}')
        grid[(lon, lat)] = number(value, 'ovation')
    if len(grid) != 360 * 181 or None in grid.values() or any(v != int(v) or not 0 <= v <= 100 for v in grid.values()):
        raise FeedError(f'ovation: grid incomplete or out of range ({len(grid)} cells)')
    rows = [[int(grid[(lon, lat)]) for lon in range(360)] for lat in range(-90, 91)]
    quality = f'observed {obs}'
    samples, edges = [], {}
    for hemisphere, sign, lats in (('N', 1, range(1, 91)), ('S', -1, range(-90, 0))):
        top = max(((grid[(lon, lat)], -abs(lat), -lon) for lon in range(360) for lat in lats))
        topValue, topLat, topLon = top[0], abs(top[1]), -top[2]
        sm, reach, reachLon, cover = ovalEdges(rows, sign)
        faintSm, faint, faintLon, faintCover = ovalEdges(rows, sign, OVAL_T_FAINT)
        edges[hemisphere] = sm
        edges[hemisphere + 'Faint'] = faintSm
        samples += [sample(f'ovationMax{hemisphere}', forecast, topValue, 'index', quality),
                    sample(f'ovationMax{hemisphere}Lat', forecast, float(sign * topLat), 'deg', quality),
                    sample(f'ovationMax{hemisphere}Lon', forecast, float(lonWest180(topLon)), 'deg', quality),
                    sample(f'ovationEdge{hemisphere}', forecast, reach, 'deg', quality),
                    sample(f'ovationEdge{hemisphere}Lon', forecast, reachLon, 'deg', quality),
                    sample(f'ovationEdge{hemisphere}Cover', forecast, float(cover), 'lon', quality),
                    sample(f'ovationEdge{hemisphere}Faint', forecast, faint, 'deg', quality),
                    sample(f'ovationEdge{hemisphere}FaintLon', forecast, faintLon, 'deg', quality),
                    sample(f'ovationEdge{hemisphere}FaintCover', forecast, float(faintCover), 'lon', quality)]
    return samples, [], [('ovation', forecast, {'obs': obs, 'forecast': forecast, 'latMin': -90, 'lonMin': 0, 'step': 1,
                                                 'rows': rows, 'edgeN': edges['N'], 'edgeS': edges['S'],
                                                 'edgeFaintN': edges['NFaint'], 'edgeFaintS': edges['SFaint']})]


def subsolarPoint(moment):
    """(latitude, longitude east -180..180) in degrees of the point where the Sun is overhead at the UTC datetime
    (declination and equation of time from the usual day-of-year series; good to a degree or so)."""
    day = moment.timetuple().tm_yday + (moment.hour + moment.minute / 60) / 24
    declination = -math.degrees(math.asin(0.39779 * math.cos(math.radians(0.98565 * (day + 10) + 1.914 * math.sin(math.radians(0.98565 * (day - 2)))))))
    b = math.radians(360 / 364 * (day - 81))
    equation = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)       # minutes
    hours = moment.hour + moment.minute / 60 + moment.second / 3600
    longitude = (12 - hours - equation / 60) * 15
    return declination, (longitude + 180) % 360 - 180


def parseDrap(text):
    """drap_global_frequencies.txt: a '# Product Valid At' time, the X-ray and
    proton messages, a header row of 90 longitudes (-178 to 178, step 4) and 90
    rows of 'lat | 90 values' (lat 89 down to -89, step 2): the highest
    affected frequency in MHz. Samples: drapMax (the global maximum) and drapMaxLat and
    drapMaxLon (where). Under a quiet Sun a whole block of cells ties at the maximum (the
    subsolar block, 154 cells on 24 Oct 2026), so the location reported is the TIED CELL
    NEAREST THE SUBSOLAR POINT, not the first in table order.
    Map drapGlobal: {valid, lonMin, lonStep, latMax, latStep, tenths: rows of
    90 integers (MHz x 10), xray, proton}."""
    lines = text.splitlines()
    valid = re.search(r'^# Product Valid At : (\d{4}-\d\d-\d\d \d\d:\d\d) UTC', text, re.M)
    if not valid:
        raise FeedError('drap: no valid-at time')
    ts = utcText(valid.group(1).replace(' ', '_'))
    messages = {}
    for key in ('X-RAY Message', 'Proton Message'):
        found = re.search(rf'^#\s+{key} : (.*)$', text, re.M)
        messages[key] = found.group(1).strip() if found else ''
    header = next((l for l in lines if re.match(r'^\s+-178\s', l)), None)
    if header is None or header.split() != [str(x) for x in range(-178, 179, 4)]:
        raise FeedError('drap: unexpected longitude header')
    table = {}
    for line in lines:
        found = re.match(r'^\s*(-?\d+) \|(.*)$', line)
        if found:
            values = found.group(2).split()
            if len(values) != 90 or int(found.group(1)) in table:
                raise FeedError(f'drap: unexpected row at latitude {found.group(1)}')
            table[int(found.group(1))] = [number(v, 'drap', True) for v in values]
    if sorted(table) != list(range(-89, 90, 2)) or any(v is None for r in table.values() for v in r):
        raise FeedError('drap: expected 90 latitude rows of 90 values')
    top = max(max(r) for r in table.values())
    sunLat, sunLon = subsolarPoint(datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ'))
    best = None
    for lat in range(89, -90, -2):
        for col, value in enumerate(table[lat]):
            if value == top:
                lon = -178 + 4 * col
                distance = math.hypot(lat - sunLat, ((lon - sunLon + 180) % 360 - 180) * math.cos(math.radians(lat)))
                if best is None or distance < best[0]:
                    best = (distance, lat, lon)
    quality = f'{messages["X-RAY Message"]}; {messages["Proton Message"]}'[:120]
    samples = [sample('drapMax', ts, top, 'MHz', quality),
               sample('drapMaxLat', ts, float(best[1]), 'deg', quality),
               sample('drapMaxLon', ts, float(best[2]), 'deg', quality)]
    maps = [('drapGlobal', ts, {'valid': ts, 'lonMin': -178, 'lonStep': 4, 'latMax': 89, 'latStep': -2,
                                'tenths': [[int(round(v * 10)) for v in table[l]] for l in range(89, -90, -2)],
                                'xray': messages['X-RAY Message'], 'proton': messages['Proton Message']})]
    return samples, [], maps


# --- swpcSlow feeds -------------------------------------------------------------

def l1Quality(r):
    return r['source'] + (f' q{r["overall_quality"]}' if r['overall_quality'] else '')


def parseL1(text, what, columns):
    """The L1 real-time solar-wind files: keep only rows flagged active."""
    kept = 0
    rows = []
    for r in recordList(loadJson(text), what):
        need(r, ('time_tag', 'active', 'source', 'overall_quality') + tuple(c for c, _, _ in columns), what)
        if not isinstance(r['active'], bool):
            raise FeedError(f'{what}: active must be true or false')
        if not r['active']:
            continue
        kept += 1
        ts = utcText(r['time_tag'])
        for column, series, unit in columns:
            rows.append(sample(series, ts, number(r[column], f'{what}.{column}'), unit, l1Quality(r)))
    if not kept:
        raise FeedError(f'{what}: no row flagged active')
    return rows, []


def parseMag(text):
    return parseL1(text, 'l1Mag', (('bt', 'l1MagBt', 'nT'), ('bx_gsm', 'l1MagBxGSM', 'nT'),
                                   ('by_gsm', 'l1MagByGSM', 'nT'), ('bz_gsm', 'l1MagBzGSM', 'nT')))


def parseWind(text):
    return parseL1(text, 'l1Wind', (('proton_speed', 'l1WindSpeed', 'km/s'),
                                    ('proton_density', 'l1WindDensity', 'cm-3'),
                                    ('proton_temperature', 'l1WindTemperature', 'K')))


F107_BURST = 0.15       # a reading this far from the median of its day's three readings is flagged


def parseF107(text):
    """Three readings a day (Morning, Noon, Afternoon), each with the trailing mean of the last
    90 Noon readings (the Noon record only). The Noon reading is the official daily value: it is
    ALSO stored as `swpcF107Daily`, the series to chart. A reading more than F107_BURST from the
    MEDIAN of its day's three readings is marked ' burst?' in the quality (a flare's 10.7 cm burst:
    207 sfu on 13 Oct 2026, a B9.9 flare minutes earlier). The median, not the Noon value, is the anchor:
    a Noon anchor would flag the two clean readings on exactly the days Noon is the burst. With fewer
    than three readings in a day nothing is flagged."""
    records = recordList(loadJson(text), 'f107')
    for r in records:
        need(r, ('time_tag', 'flux', 'reporting_schedule', 'ninety_day_mean'), 'f107')
    byDay = {}
    for r in records:
        byDay.setdefault(utcText(r['time_tag'])[:10], []).append(number(r['flux'], 'f107'))
    anchor = {day: statistics.median(v) for day, v in byDay.items() if len(v) == 3 and None not in v}
    rows = []
    for r in records:
        ts, value, schedule = utcText(r['time_tag']), number(r['flux'], 'f107'), r['reporting_schedule']
        reference = anchor.get(ts[:10])
        quality = schedule
        if value is not None and reference and abs(value - reference) / reference > F107_BURST:
            quality += ' burst?'
        rows.append(sample('swpcF107', ts, value, 'sfu', quality))
        if schedule == 'Noon':
            rows.append(sample('swpcF107Daily', ts, value, 'sfu', 'Noon'))
        if r['ninety_day_mean'] is not None:
            rows.append(sample('swpcF107Mean90', ts, number(r['ninety_day_mean'], 'f107'), 'sfu',
                               'trailing mean of the last 90 Noon readings'))
    return rows, []


# NOAA labels the 45-day ap 'nT'; Ap is unitless (multiply by 2 nT for the disturbance at 50 degrees geomagnetic
# latitude, GFZ's file header), so it is stored in the same unit as the 27-day outlook and GFZ's daily index.
UNIT_OVERRIDE = {'ap': 'Ap'}


def parse45Day(text):
    data = loadJson(text)
    if not isinstance(data, dict) or not isinstance(data.get('data'), list) or not isinstance(data.get('units'), dict):
        raise FeedError('45-day: expected data and units')
    need(data, ('issued',), '45-day')
    series = {'ap': 'swpcForecastAp', 'f107': 'swpcForecastF107'}
    quality = f'issued {utcText(data["issued"])[:10]}'
    rows = []
    for r in recordList(data['data'], '45-day'):
        need(r, ('time', 'metric', 'value'), '45-day')
        if r['metric'] not in series or r['metric'] not in data['units']:
            raise FeedError(f'45-day: unexpected metric {r["metric"]!r}')
        rows.append(sample(series[r['metric']], utcText(r['time']), number(r['value'], '45-day'),
                           UNIT_OVERRIDE.get(r['metric'], data['units'][r['metric']]), quality))
    return rows, []


def parseFlares(text):
    """The 7-day GOES flare list. An empty list is a quiet week."""
    events = []
    for r in recordList(loadJson(text), 'flares', nonEmpty=False):
        need(r, ('begin_time', 'max_class', 'satellite'), 'flares')
        start = utcText(r['begin_time'])
        events.append(('flare', start, f'{start} GOES-{r["satellite"]}', r))
    return [], events


def repairText(value):
    """SWPC's radio-flux quality text arrives as UTF-8 read as Windows-1252
    ('Uncertain â€“ unknown cause'); undo that where it applies."""
    try:
        return value.encode('cp1252').decode('utf-8')
    except (UnicodeError, AttributeError):
        return value


def parseRadioFlux(text):
    """One record per observatory reading, with a flux per frequency."""
    events = []
    for r in recordList(loadJson(text), 'radioFlux'):
        need(r, ('time_tag', 'common_name', 'details'), 'radioFlux')
        if not isinstance(r['details'], list) or not all(isinstance(d, dict) for d in r['details']):
            raise FeedError('radioFlux: details must be a list of objects')
        for d in r['details']:
            need(d, ('frequency', 'flux'), 'radioFlux.details')
            if 'observed_quality' in d:
                d['observed_quality'] = repairText(d['observed_quality'])
        start = utcText(r['time_tag'])
        events.append(('radioFlux', start, f'{r["common_name"]}|{start}', r))
    return [], events


def parseEvents(text):
    """edited_events.json: flares, bursts and sweeps reported by the
    observatories, about 30 days. The type (XRA, FLA, RBR, RSP, ...) is the
    eventType; observatory, report number, start, frequency and bin make
    the ID (unique across a month's 762 records)."""
    events = []
    for r in recordList(loadJson(text), 'events'):
        need(r, ('type', 'observatory', 'obsid', 'begin_datetime', 'frequency', 'bin'), 'events')
        start = utcText(r['begin_datetime'])
        eventID = f'{r["observatory"]}|{r["type"]}|{r["obsid"]}|{start}|{r["frequency"]}|{r["bin"]}'
        events.append((str(r['type']), start, eventID, r))
    return [], events


KP_STATES = ('observed', 'estimated', 'predicted')


def parseKp(text):
    """Planetary Kp, 3-hourly: observed, estimated (NOAA's own, from 8
    stations) and predicted. GFZ's official Kp is a separate series."""
    rows = []
    for r in recordList(loadJson(text), 'kp'):
        need(r, ('time_tag', 'kp', 'observed'), 'kp')
        if r['observed'] not in KP_STATES:
            raise FeedError(f'kp: unexpected state {r["observed"]!r}')
        rows.append(sample('swpcKp', utcText(r['time_tag']), number(r['kp'], 'kp'), 'Kp', r['observed']))
    return rows, []


def parseDst(text):
    """Kyoto's real-time (quick-look) Dst as copied by SWPC; Kyoto later replaces it with provisional and final
    values, so the quality is 'realtime'. Whether time_tag marks the start or the end of Kyoto's hour is not documented."""
    rows = []
    for r in recordList(loadJson(text), 'dst'):
        need(r, ('time_tag', 'dst'), 'dst')
        rows.append(sample('swpcDst', utcText(r['time_tag']), number(r['dst'], 'dst'), 'nT', 'realtime'))
    return rows, []


def issuedOf(text):
    found = re.search(r'^:Issued:\s+(\d{4}) (\w{3}) (\d{1,2}) (\d{2})(\d{2}) UTC', text, re.M)
    if not found or found.group(2) not in MONTHS:
        raise FeedError('forecast text: no ":Issued:" line')
    year, month, day, hour, minute = (int(found.group(1)), MONTHS[found.group(2)], int(found.group(3)),
                                      int(found.group(4)), int(found.group(5)))
    return datetime(year, month, day, hour, minute)


def forecastDay(month, day, issued):
    """'Oct', '24' -> the date in the issue's year (next year if that would
    put it more than half a year before the issue: a December issue)."""
    if month not in MONTHS:
        raise FeedError(f'forecast text: unknown month {month!r}')
    date = datetime(issued.year, MONTHS[month], int(day))
    return date.replace(year=date.year + 1) if date < issued - timedelta(days=180) else date


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def parse3Day(text):
    """The 3-day forecast: the Kp table (eight 3-hour blocks x 3 days), the
    S1, R1-R2 and R3 probabilities, and the whole text as an event."""
    issued = issuedOf(text)
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if line.startswith('00-03UT')), None)
    if first is None or first == 0:
        raise FeedError('3-day: no Kp table')
    days = re.findall(r'([A-Z][a-z]{2}) (\d{1,2})', lines[first - 1])
    if len(days) != 3:
        raise FeedError('3-day: Kp table header has no three dates')
    dates = [forecastDay(m, d, issued) for m, d in days]
    quality = f'issued {stamp(issued)}'
    rows = []
    for block in range(8):
        found = re.match(r'(\d\d)-(\d\d)UT\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$',
                         lines[first + block]) if first + block < len(lines) else None
        if not found or int(found.group(1)) != block * 3:
            raise FeedError(f'3-day: Kp row {block + 1} not as expected')
        for date, value in zip(dates, found.groups()[2:]):
            rows.append(sample('swpcForecast3dayKp', stamp(date + timedelta(hours=block * 3)), float(value), 'Kp', quality))
    for label, series in (('S1 or greater', 'swpcForecast3dayS1Prob'), ('R1-R2', 'swpcForecast3dayR1R2Prob'),
                          ('R3 or greater', 'swpcForecast3dayR3Prob')):
        found = next((m for m in (re.match(re.escape(label) + r'\s+(\d+)%\s+(\d+)%\s+(\d+)%\s*$', line)
                                  for line in lines) if m), None)
        if not found:
            raise FeedError(f'3-day: no "{label}" row')
        for date, value in zip(dates, found.groups()):
            rows.append(sample(series, stamp(date), float(value), '%', quality))
    return rows, [('forecast3day', stamp(issued), stamp(issued), {'issued': stamp(issued), 'text': text})]


def parse27Day(text):
    """The 27-day outlook table: date, F10.7, Ap, largest Kp; and the text
    as an event."""
    issued = issuedOf(text)
    quality = f'issued {stamp(issued)}'
    rows = []
    for line in text.splitlines():
        found = re.fullmatch(r'(\d{4}) (\w{3}) (\d{2})\s+(\d+)\s+(\d+)\s+(\d+)\s*', line)
        if not found:
            continue
        if found.group(2) not in MONTHS:
            raise FeedError(f'27-day: unknown month in {line!r}')
        ts = stamp(datetime(int(found.group(1)), MONTHS[found.group(2)], int(found.group(3))))
        for series, unit, value in (('swpcOutlook27F107', 'sfu', found.group(4)), ('swpcOutlook27Ap', 'Ap', found.group(5)),
                                    ('swpcOutlook27Kp', 'Kp', found.group(6))):
            rows.append(sample(series, ts, float(value), unit, quality))
    if len(rows) < 3 * 20:
        raise FeedError(f'27-day: only {len(rows) // 3} data lines')
    return rows, [('outlook27day', stamp(issued), stamp(issued), {'issued': stamp(issued), 'text': text})]


# --- Feeds and jobs -------------------------------------------------------------

# name -> (path under BASE_URL, parser). A parser takes the body text and
# returns (sample rows, event rows), or raises FeedError.
FEEDS = {
    'scales': ('products/noaa-scales.json', parseScales),
    'kp1m': ('json/planetary_k_index_1m.json', parseKp1m),
    'protons': ('json/goes/primary/integral-protons-6-hour.json', parseProtons),
    'xray': ('json/goes/primary/xrays-6-hour.json', parseXray),
    'hemiPower': ('text/aurora-nowcast-hemi-power.txt', parseHemiPower),
    'l1Mag': ('json/rtsw/rtsw_mag_1m.json', parseMag),
    'l1Wind': ('json/rtsw/rtsw_wind_1m.json', parseWind),
    'f107': ('json/f107_cm_flux.json', parseF107),
    'forecast45': ('json/45-day-forecast.json', parse45Day),
    'flares': ('json/goes/primary/xray-flares-7-day.json', parseFlares),
    'radioFlux': ('json/solar-radio-flux.json', parseRadioFlux),
    'events': ('json/edited_events.json', parseEvents),
    'kp': ('products/noaa-planetary-k-index-forecast.json', parseKp),
    'dst': ('products/kyoto-dst.json', parseDst),
    'forecast3day': ('text/3-day-forecast.txt', parse3Day),
    'outlook27day': ('text/27-day-outlook.txt', parse27Day),
    'ovation': ('json/ovation_aurora_latest.json', parseOvation),
    'drap': ('text/drap_global_frequencies.txt', parseDrap),
}

JOBS = {
    JOB_FAST: ('scales', 'kp1m', 'protons', 'xray', 'hemiPower'),
    JOB_SLOW: ('l1Mag', 'l1Wind', 'f107', 'forecast45', 'flares', 'radioFlux', 'events', 'kp', 'dst',
               'forecast3day', 'outlook27day'),
    JOB_MAPS: ('ovation', 'drap'),
}


def runIngestion(db, fetch=None, job=JOB_FAST):
    """Every feed of `job`, each independent of the others' failure: it is
    parsed and validated whole, then stored in one transaction. Returns
    (changes, failed, note)."""
    fetch = fetch or PacedFetcher()
    changes, failures, notes = 0, [], []
    for name in JOBS[job]:
        path, parse = FEEDS[name]
        try:
            parsed = parse(fetch(BASE_URL + path))
            samples, events = parsed[0], parsed[1]
            maps = parsed[2] if len(parsed) > 2 else ()
            changed = storeFeed(db, samples, events, maps=maps)
            changes += changed
            notes.append(f'{name} {len(samples) + len(events) + len(maps)}')
            print(f'  {name}: {len(samples)} samples, {len(events)} events, {len(maps)} maps, {changed} changed')
        except Exception as error:
            failures.append(f'{name}: {type(error).__name__}: {error}')
            print(f'  {name}: ERROR {error} -- nothing stored from it')
    note = ', '.join(notes) + ('; FAILED ' + '; '.join(failures) if failures else '')
    return changes, bool(failures), note[:500]


def pruneJob(db, now=None):
    """The swpcPrune job. Returns (rows deleted, failed, note)."""
    removed = pruneOldOneMinute(db, now or datetime.utcnow())
    note = ', '.join(f'{name} {count}' for name, count in sorted(removed.items())) or 'nothing older than the window'
    print(f'  prune: {sum(removed.values())} rows deleted')
    return sum(removed.values()), False, note[:500]


def main(argv=None):
    parser = argparse.ArgumentParser(description='NOAA SWPC ingestion')
    parser.add_argument('--job', choices=sorted(JOBS) + [JOB_PRUNE], required=True)
    args = parser.parse_args(argv)
    db = openDb()
    print(f'\n=== [{time.strftime("%H:%M:%S")}] NOAA SWPC ingestion ({args.job}) ===')
    with trackRun(db, args.job) as run:
        run.changes, run.failed, run.note = pruneJob(db) if args.job == JOB_PRUNE else runIngestion(db, job=args.job)
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} changes')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
