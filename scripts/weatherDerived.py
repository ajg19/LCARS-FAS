"""Derived space-weather quantities, computed when the weather site file is built
(publishSite.publishWeather) from what the ingestion databases hold. Pure functions,
so they can be tested without a database.

They put into practice the verdicts in enterpriseCrewOutput/spock_dbDataQuestions_2026-10-24.md:

  newellRate      (item 3) the Newell et al. (2007, JGR 112, A01206) solar-wind driving function
                  dPhi/dt = v^(4/3) B_T^(2/3) |sin(theta/2)|^(8/3), with B_T = sqrt(By^2 + Bz^2) in
                  GSM and theta = atan2(By, Bz). Computed per minute where speed, By and Bz all
                  exist; hourly means only from at least HOURLY_MIN_MINUTES such minutes. The
                  values are for L1; Earth sees them 45 to 70 minutes later.
  gLevel          (item 4) NOAA's G level for a Kp value, thirds included: G1 4.67-5.33, G2 5.67-6.33,
                  G3 6.67-7.33, G4 7.67-8.67, G5 9.00.
  stormRuns       (item 11) the storm list from GFZ Kp: a run of 3-hour blocks with Kp >= 4.67; its level
                  is the highest G in the run; the causal links (CME, IPS, HSS) come from DONKI's GST
                  records, matched within one block.
  sEvents         (item 10) NOAA's S-event definition on the >10 MeV channel: starts at the first of three
                  consecutive 5-minute values at or above 10 pfu, ends at the last value at or above 10 pfu.
  sepGroups       (item 10) DONKI SEP records grouped one marker per event: STEREO-A records dropped,
                  GOES and SOHO records are observations, MODEL records (REleASE) are forecasts.
  cmeSelect       (item 12) which CMEs to show: any analysis with an ENLIL-predicted Earth arrival (or an
                  Earth glancing/minor impact) or a leading-edge speed of 1000 km/s or more (48 of the 334 CMEs of 26 Jul to 24 Oct 2026); the leading-edge (LE)
                  analysis is the one to take for speed, type and half-angle.
  earthStreams    (item 13) DONKI high-speed streams seen at L1 (a positive list of spacecraft), the
                  interplanetary shocks located at Earth, and a recurrence hint from STEREO-A streams
                  (a stream seen there returns to Earth about 22 days later if its coronal hole persists).
  f107Bursts      (second review, item 1) F10.7 daily values taken during a flare radio burst: a day whose value
                  exceeds 1.15 x the mean of the day before and the day after, or (SWPC's three readings) whose Noon
                  reading exceeds 1.15 x the larger of Morning and Afternoon. The three known days are 2026-01-18,
                  2026-07-01 and 2026-09-02. GFZ's daily value is the single 20 UT reading, so there is no 'Noon check'.
  f107Clean       the daily observed flux with flagged days replaced by the median of the day's three readings (where SWPC
                  has them) or the mean of the neighbours; what the 81-day mean and the drag work use.
  f107Centred     (item 5) the CENTRED 81-day mean of the cleaned OBSERVED flux (NRLMSISE-00's F10.7A, JB2008's F81c): no
                  partial windows; the newest 40 days are filled from SWPC's 45-day forecast and labelled as such.
  dailyFlareMax   (item 9) the largest flare of each UT day from SWPC's edited events (type XRA) of the
                  primary GOES satellite only; XRA lists every flare twice, once per satellite.
"""

import math
from datetime import datetime, timedelta

F107_BURST = 1.15            # a daily value this far above the mean of the days either side, or above the day's other readings
F107_HALF_WINDOW = 40        # the 81-day mean is centred: 40 days either side
F107_MIN_DAYS = 75           # of the 81 (GFZ has gaps, e.g. 2026-05-09)
HOURLY_MIN_MINUTES = 30
NEWELL_UNIT = '(km/s)^(4/3) nT^(2/3)'
STORM_KP = 4.66                      # Kp 4.67 (5-) is the lowest G1 block
G_STEPS = ((8.99, 5), (7.66, 4), (6.66, 3), (5.66, 2), (STORM_KP, 1))
S_EVENT_PFU = 10.0
S_EVENT_RUN = 3
CME_FAST_KMS = 1000
L1_SPACECRAFT = ('SOLAR-1', 'ACE', 'IMAP', 'DSCOVR', 'WIND')
RECURRENCE_DAYS = 22
STAMP = '%Y-%m-%dT%H:%M:%SZ'


def parseStamp(text):
    """'2026-10-24T18:00:00Z' or DONKI's '2026-10-24T18:00Z' (seconds and Z optional) -> datetime."""
    text = text.rstrip('Z')
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%S' if len(text) > 16 else '%Y-%m-%dT%H:%M')


def stamp(moment):
    return moment.strftime(STAMP)


# --- Newell function -------------------------------------------------------------------------

def newellRate(speed, by, bz):
    """(km/s)^(4/3) nT^(2/3); None if any input is missing."""
    if speed is None or by is None or bz is None:
        return None
    transverse = math.hypot(by, bz)
    theta = math.atan2(by, bz)
    return speed ** (4 / 3) * transverse ** (2 / 3) * abs(math.sin(theta / 2)) ** (8 / 3)


def newellSeries(rows):
    """rows: (tsUtc, speed, by, bz) -> ([(tsUtc, rate)] per minute, [(hourUtc, mean, minutes)] hourly)."""
    minutes, hours = [], {}
    for ts, speed, by, bz in rows:
        rate = newellRate(speed, by, bz)
        if rate is None:
            continue
        minutes.append((ts, rate))
        hours.setdefault(ts[:13] + ':00:00Z', []).append(rate)
    hourly = [(hour, sum(v) / len(v), len(v)) for hour, v in sorted(hours.items()) if len(v) >= HOURLY_MIN_MINUTES]
    return minutes, hourly


# --- Storms -------------------------------------------------------------------------------------

def gLevel(kp):
    if kp is None:
        return 0
    return next((level for floor, level in G_STEPS if kp >= floor), 0)


def stormRuns(kpRows, gstRecords=()):
    """kpRows: (blockStartUtc, kp, quality) in time order, the GFZ Kp. gstRecords: DONKI GST records (dicts).
    -> [{startUtc, endUtc, maxKp, level, blocks, preliminary, gst, links}]."""
    storms, run = [], []

    def close():
        if run:
            kps = [r[1] for r in run]
            storms.append({'startUtc': run[0][0], 'endUtc': stamp(parseStamp(run[-1][0]) + timedelta(hours=3)),
                           'maxKp': max(kps), 'level': gLevel(max(kps)), 'blocks': len(run),
                           'preliminary': any(r[2] == 'pre' for r in run), 'gst': [], 'links': []})
    for ts, kp, quality in kpRows:
        contiguous = run and parseStamp(ts) - parseStamp(run[-1][0]) == timedelta(hours=3)
        if kp is not None and kp >= STORM_KP:
            if run and not contiguous:
                close()
                run = []
            run.append((ts, kp, quality))
        else:
            close()
            run = []
    close()
    block = timedelta(hours=3)
    for record in gstRecords:
        # DONKI's observedTime marks the END of the 3-hour block; GFZ stamps the start
        starts = [parseStamp(k['observedTime']) - block for k in record.get('allKpIndex') or [] if k.get('observedTime')]
        for storm in storms:
            begin, end = parseStamp(storm['startUtc']), parseStamp(storm['endUtc'])
            if any(begin - block <= s <= end for s in starts):
                storm['gst'].append(record.get('gstID'))
                storm['links'] += [e['activityID'] for e in record.get('linkedEvents') or []
                                   if any(tag in e.get('activityID', '') for tag in ('-CME-', '-IPS-', '-HSS-'))]
    return storms


# --- Energetic protons ----------------------------------------------------------------------------

def sEvents(rows):
    """rows: (tsUtc, flux) of the >10 MeV channel, 5-minute, in time order.
    -> [{startUtc, endUtc, peakPfu, peakUtc}]. A run is consecutive 5-minute values at or above 10 pfu; it is an
    event if at least three long; the event starts at the first value and ends at the last one."""
    events, run = [], []

    def close():
        if len(run) >= S_EVENT_RUN:
            peak = max(run, key=lambda r: r[1])
            events.append({'startUtc': run[0][0], 'endUtc': run[-1][0], 'peakPfu': peak[1], 'peakUtc': peak[0]})
    for ts, flux in rows:
        if flux is not None and flux >= S_EVENT_PFU and (not run or parseStamp(ts) - parseStamp(run[-1][0]) == timedelta(minutes=5)):
            run.append((ts, flux))
            continue
        close()
        run = [(ts, flux)] if flux is not None and flux >= S_EVENT_PFU else []
    close()
    return events


def sepKind(name):
    if name.startswith('MODEL'):
        return 'forecast'
    if name.startswith('STEREO'):
        return 'stereo'
    return 'observed'


def sepGroups(records):
    """DONKI SEP records (dicts) -> one dict per event: the records are grouped by the flare or CME they link to
    (or by day when unlinked); STEREO-A records are left out; a group of model records only is a forecast."""
    groups = {}
    for record in records:
        if not record.get('eventTime'):
            continue
        instruments = [i.get('displayName', '') for i in record.get('instruments') or []]
        kinds = {sepKind(n) for n in instruments}
        if kinds <= {'stereo'}:
            continue
        links = sorted(e['activityID'] for e in record.get('linkedEvents') or []
                       if any(tag in e.get('activityID', '') for tag in ('-FLR-', '-CME-')))
        key = links[0] if links else record['eventTime'][:10]
        group = groups.setdefault(key, {'key': key, 'startUtc': None, 'links': set(), 'observed': [], 'forecast': []})
        when = record['eventTime'][:16] + ':00Z'
        group['startUtc'] = when if group['startUtc'] is None or when < group['startUtc'] else group['startUtc']
        group['links'].update(links)
        for name in instruments:
            if sepKind(name) in ('observed', 'forecast'):
                group[sepKind(name)].append(name)
    out = []
    for group in groups.values():
        group['links'] = sorted(group['links'])
        group['observed'], group['forecast'] = sorted(set(group['observed'])), sorted(set(group['forecast']))
        group['status'] = 'observed' if group['observed'] else 'forecast'
        out.append(group)
    return sorted(out, key=lambda g: g['startUtc'])


# --- CMEs, streams, shocks --------------------------------------------------------------------------

def cmeAnalyses(record):
    return record.get('cmeAnalyses') or []


def cmeLeadingEdge(record):
    """The analysis to read speed, type and half-angle from: the most accurate leading-edge (LE) one."""
    le = [a for a in cmeAnalyses(record) if a.get('featureCode') == 'LE']
    return next((a for a in le if a.get('isMostAccurate')), le[0] if le else None)


def cmeEarthBound(record):
    for analysis in cmeAnalyses(record):
        for run in analysis.get('enlilList') or []:
            if run.get('estimatedShockArrivalTime') or run.get('isEarthGB') or run.get('isEarthMinorImpact'):
                return True
    return False


def cmeShown(record):
    """True for the CMEs worth a mark on the timeline: ENLIL gives an Earth arrival, or it is fast."""
    return cmeEarthBound(record) or ((cmeLeadingEdge(record) or {}).get('speed') or 0) >= CME_FAST_KMS


def cmeSummary(record):
    le = cmeLeadingEdge(record) or {}
    arrivals = sorted(run['estimatedShockArrivalTime'] for a in cmeAnalyses(record) for run in a.get('enlilList') or []
                      if run.get('estimatedShockArrivalTime'))
    return {'activityID': record.get('activityID'), 'startUtc': record.get('startTime'), 'speed': le.get('speed'),
            'type': le.get('type'), 'halfAngle': le.get('halfAngle'), 'latitude': le.get('latitude'),
            'longitude': le.get('longitude'), 'earthBound': cmeEarthBound(record),
            'predictedArrival': arrivals[0] if arrivals else None}


def atL1(record):
    return any(i.get('displayName', '').split(':')[0] in L1_SPACECRAFT for i in record.get('instruments') or [])


def earthStreams(hssRecords, ipsRecords):
    """-> (hssAtL1, ipsAtEarth, recurrence): the streams a spacecraft at L1 saw, the shocks logged at Earth, and for
    each STEREO-A-only stream the date it may return to Earth (+22 days, give or take 3)."""
    l1 = [r for r in hssRecords if atL1(r)]
    shocks = [r for r in ipsRecords if r.get('location') == 'Earth']
    recurrence = []
    for r in hssRecords:
        if r.get('eventTime') and not atL1(r) and any(i.get('displayName', '').startswith('STEREO A') for i in r.get('instruments') or []):
            seen = parseStamp(r['eventTime'][:16] + ':00Z')
            recurrence.append({'hssID': r.get('hssID'), 'seenUtc': stamp(seen),
                               'expectedUtc': stamp(seen + timedelta(days=RECURRENCE_DAYS)), 'plusMinusDays': 3})
    return l1, shocks, recurrence


# --- F10.7 (second review) ---------------------------------------------------------------------------------

def shiftDay(day, days):
    return (datetime.strptime(day, '%Y-%m-%d') + timedelta(days=days)).strftime('%Y-%m-%d')


def f107Bursts(obs, readings=None):
    """obs: {day: observed daily flux or None}; readings: {day: (morning, noon, afternoon)} from SWPC.
    -> {day: 'neighbours' | 'same day'}: the days to flag 'burst?'."""
    flagged = {}
    for day, value in obs.items():
        before, after = obs.get(shiftDay(day, -1)), obs.get(shiftDay(day, 1))
        if value is not None and before is not None and after is not None and value > F107_BURST * (before + after) / 2:
            flagged[day] = 'neighbours'
    for day, trio in (readings or {}).items():
        if len(trio) == 3 and None not in trio and trio[1] > F107_BURST * max(trio[0], trio[2]):
            flagged.setdefault(day, 'same day')
    return flagged


def f107Clean(obs, flagged, readings=None):
    """-> {day: (value, how)}: the observed flux with each flagged day replaced by the median of its three readings where
    SWPC has them, else the mean of the neighbours; days without a value are absent."""
    clean = {}
    for day, value in obs.items():
        if value is None:
            continue
        trio = (readings or {}).get(day)
        if day not in flagged:
            clean[day] = (value, 'observed')
        elif trio and len(trio) == 3 and None not in trio:
            clean[day] = (sorted(trio)[1], 'cleaned: median of the three readings')
        else:
            before, after = obs.get(shiftDay(day, -1)), obs.get(shiftDay(day, 1))
            clean[day] = ((before + after) / 2, 'cleaned: mean of the neighbours') if before is not None and after is not None \
                else (value, 'burst? not cleaned')
    return clean


def f107Centred(clean, forecast=None):
    """clean: {day: value}; forecast: {day: value} (SWPC's 45-day forecast, used only after the last observed day).
    -> {day: (mean, 'observed' | 'forecast')}: the mean of the 81 days d-40..d+40, only where the whole window lies inside
    the record (no partial windows) and at least F107_MIN_DAYS of the 81 have a value; 'forecast' where the window reaches
    into the forecast."""
    if not clean:
        return {}
    first, last = min(clean), max(clean)
    combined = dict(clean)
    for day, value in (forecast or {}).items():
        if day > last and value is not None:
            combined[day] = value
    end = max(combined)
    out = {}
    day = shiftDay(first, F107_HALF_WINDOW)
    while day <= shiftDay(end, -F107_HALF_WINDOW):
        window = [shiftDay(day, k) for k in range(-F107_HALF_WINDOW, F107_HALF_WINDOW + 1)]
        values = [combined[d] for d in window if d in combined]
        if len(values) >= F107_MIN_DAYS:
            out[day] = (sum(values) / len(values), 'forecast' if any(d > last for d in window if d in combined) else 'observed')
        day = shiftDay(day, 1)
    return out


# --- Flares -----------------------------------------------------------------------------------------

def dailyFlareMax(xraRecords, observatory):
    """xraRecords: SWPC edited-event XRA records; observatory: 'G18' (the primary satellite's code).
    -> {day: (peakFlux W/m2, class text, peakTimeUtc)} by the UT date of each flare's peak."""
    best = {}
    for r in xraRecords:
        if r.get('observatory') != observatory or not r.get('max_datetime'):
            continue
        try:
            flux = float(r['particulars10'])
        except (TypeError, ValueError, KeyError):
            continue
        peak = r['max_datetime'][:19] + 'Z'
        day = peak[:10]
        if day not in best or flux > best[day][0]:
            best[day] = (flux, r.get('particulars1'), peak)
    return best
