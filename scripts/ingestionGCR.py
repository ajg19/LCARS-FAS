"""Galactic cosmic ray ingestion: keeps databases/ingestionGCR.db holding the
neutron-monitor count rates of the Oulu cosmic ray station (Sodankyla
Geophysical Observatory, University of Oulu), read from the station's own
online query (cosmicrays.oulu.fi/webform/onlinequery.cgi, a plain GET that
answers CSV; no key or login).

For the GCR view: 0_documentation/plans/spaceWeatherChartsPlan.md, section 4.
Fetches and stores only; the publish step decides what reaches the website.

Credit (required by the station, https://cosmicrays.oulu.fi/readme.html):
"Data are intended strictly for research/educational purposes and public
non-commercial services. In a case of commercial use, please contact the
station manager. Users of the data are expected to acknowledge this web-site
and the Sodankyla Geophysical Observatory." Station manager: Ilya Usoskin
(Ilya.Usoskin@oulu.fi). Data from Dome C should additionally be acknowledged
as obtained due to support of the French-Italian Concordia Station (IPEV
program n903 and PNRA Project LTCPAA PNRA14_00091). Data for the current
month are not verified by the station.

Stations (STATIONS). OULU is the reference neutron monitor (hourly since
1964). DOMC is the Dome C (Antarctica) neutron monitor, a second polar station
(about 1,040 cts/min corrected). DOMB, the second Dome C detector, is real too but
counts about a quarter as many neutrons (about 290 cts/min against 1,040), so
its hourly noise is twice DOMC's; it is left out, and is one line in STATIONS
if wanted.

Time stamps are the START of the averaging hour (hourly) or of the month (monthly): verified by Spock on
24 Oct 2026 by recomputing the hh:00 rows from 1-minute data (6 of 6 hours match; the end-of-hour
alternative misses by 13 to 26 cts/min). Dome C uses the same server and format, so the same convention
is inferred. The FractionalDate column changes meaning with the resolution and is ignored.

Reference level for the 25-year cycle chart: OULU_REFERENCE_CTS_MIN (below).

Series, per station prefix (gcrOulu, gcrDomc):
  <prefix>Corrected   pressure-corrected count rate, cts/min (the one to plot)
  <prefix>Raw         uncorrected count rate, cts/min
  <prefix>Pressure    station air pressure, mbar
  ...Monthly          the same three from the monthly means since 1964
                      (time stamp = first day of the month)
A period with no data comes back from the station as all zeros; it is stored as NULL.
Dome C's monthly record starts in March 2016.
Quality: 'verified', or 'provisional' for the month in progress; a monthly row the server splits
(its empty first days come as an all-zero row stamped on the 1st, the rest stamped on the first day with data)
is re-stamped to the 1st and says 'partial month from <date>'; Dome C monthly rows whose correction is
heavy (factor over 1.12; 8 months in 2016-19) say 'heavily corrected'. Times are UTC.

Jobs (cron via runIngestion.py):
  gcr          hourly: the last RECENT_DAYS days at 1-hour resolution, upserted.
               --backfill DAYS reads that many days instead (once, for history).
  gcrMonthly   monthly (--monthly): the whole monthly record since 1964, once a month.

Each response is validated whole before anything from it is stored; a
surprise (another header, a bad number) rejects that response and the run is
recorded as failed. Nothing here is ever deleted: the hourly data are small
(about 1.6 MB a year per station) and the monthly record is kept for good.
"""

import argparse
import csv
import io
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from dbPaths import GCR_DB, dbPath
from ingestionLog import trackRun
from spaceWeatherSamples import FeedError, PacedFetcher, connect, number, storeFeed, utcText

BASE_URL = 'https://cosmicrays.oulu.fi/webform/onlinequery.cgi'
JOB = 'gcr'
JOB_MONTHLY = 'gcrMonthly'
RECENT_DAYS = 3
CHUNK_DAYS = 366
HOURLY, MONTHLY = 60, 44640           # the server's resolution values, in minutes
FIRST_YEAR = 1964

# station code -> (series prefix, name)
STATIONS = {
    'OULU': ('gcrOulu', 'Oulu'),
    'DOMC': ('gcrDomc', 'Dome C'),
}
# Oulu's mean count rate over solar cycles 20 to 24 (Oct 1964 to Nov 2019), cts/min, corrected: the zero line of
# the 25-year cycle chart, drawn as 100 * (I / 6177 - 1) per cent. Source: Spock, enterpriseCrewOutput/
# spock_dbDataQuestions2_2026-10-24.md, section 3(c). (The full-record mean, 6181.5, or cycles 21 to 24, 6176.9, would
# move the line by less than 0.1%.) Dome C, from Nov 2019 on, when Oulu is at 6177: 1081 cts/min.
OULU_REFERENCE_CTS_MIN = 6177
DOMC_REFERENCE_CTS_MIN = 1081
HEAVY_CORRECTION = 1.12     # Dome C: corrected / (raw * exp(0.00769 * (P - 650))) above this is 'heavily corrected'
HEADER = ['Timestamp', 'FractionalDate', 'UncorrectedCountRate[cts/min]', 'CorrectedCountRate[cts/min]', 'Pressure[mbar]']


def openDb(path=None):
    return connect(path or dbPath(GCR_DB))


def utcNow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def queryUrl(station, start, end, resolution):
    half = lambda d: f'{d:%H}:{"30" if d.minute >= 30 else "00"}'   # noqa: E731 the form offers :00 and :30
    return BASE_URL + '?' + urlencode({
        'station': station, 'startday': f'{start:%d}', 'startmonth': f'{start:%m}', 'startyear': start.year,
        'starttime': half(start), 'endday': f'{end:%d}', 'endmonth': f'{end:%m}', 'endyear': end.year,
        'endtime': half(end), 'resolution': resolution, 'outputmode': 'csv'})


def parseCounts(text, station, resolution, now=None):
    """CSV -> sample rows for one station. Quality is 'provisional' for the
    month in progress, else 'verified'."""
    now = now or utcNow()
    prefix = STATIONS[station][0] + ('Monthly' if resolution == MONTHLY else '')
    thisMonth = now.strftime('%Y-%m')
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines or [h.strip() for h in next(csv.reader([lines[0]]))] != HEADER:
        raise FeedError(f'{station}: unexpected CSV header')
    records = []                      # [ts, raw, corrected, pressure, emptyPeriod, partialFrom]
    for fields in csv.reader(io.StringIO(chr(10).join(lines[1:]))):
        if len(fields) != len(HEADER):
            raise FeedError(f'{station}: unexpected line {fields!r}')
        ts = utcText(fields[0])
        raw, corrected, pressure = (number(f.strip(), f'{station} {name}', allowText=True)
                                    for f, name in zip(fields[2:], ('raw', 'corrected', 'pressure')))
        empty = raw == corrected == pressure == 0
        if empty:
            raw = corrected = pressure = None     # the station's way of saying "no data this period" (seen: Dome C, Jan 2026)
        if any(v is not None and v < 0 for v in (raw, corrected)) or (pressure is not None and not 300 <= pressure <= 1100):
            raise FeedError(f'{station}: implausible values in {fields!r}')
        records.append([ts, raw, corrected, pressure, empty, None])
    if resolution == MONTHLY:
        # The server splits a month whose first days are empty: an all-zero row stamped on the 1st and the data row
        # stamped on the first day with data (Dome C, January 2026: 2026-01-01 zeros, then 2026-01-09: 882). Drop the
        # zero row and give the data row the 1st, so joins by month find it. A month with only zeros stays NULL.
        merged = []
        for i, record in enumerate(records):
            following = records[i + 1] if i + 1 < len(records) else None
            if record[4] and following and following[0][:7] == record[0][:7] and not following[4]:
                continue
            merged.append(record)
        for i, record in enumerate(merged):
            if not record[4] and record[0][8:10] != '01':
                record[5], record[0] = record[0][:10], record[0][:8] + '01T00:00:00Z'
        records = merged
    rows = []
    for ts, raw, corrected, pressure, empty, partialFrom in records:
        quality = 'provisional' if ts[:7] >= thisMonth else 'verified'
        if partialFrom:
            quality += f'; partial month from {partialFrom}'
        if resolution == MONTHLY and station == 'DOMC' and raw and corrected and pressure                 and corrected / (raw * math.exp(0.00769 * (pressure - 650))) > HEAVY_CORRECTION:
            quality += '; heavily corrected'
        rows += [(prefix + 'Corrected', ts, corrected, 'cts/min', quality), (prefix + 'Raw', ts, raw, 'cts/min', quality),
                 (prefix + 'Pressure', ts, pressure, 'mbar', quality)]
    if not rows:
        raise FeedError(f'{station}: no data lines')
    return rows


def spans(start, end):
    """(start, end) stretches of at most CHUNK_DAYS days."""
    while start < end:
        stop = min(start + timedelta(days=CHUNK_DAYS), end)
        yield start, stop
        start = stop


def plan(now, backfillDays=0, monthly=False):
    """[(name, url, resolution, station)] of the requests this run makes."""
    out = []
    for station in STATIONS:
        if monthly:
            out.append((f'{station} monthly', queryUrl(station, datetime(FIRST_YEAR, 1, 1), now, MONTHLY), MONTHLY, station))
        else:
            days = backfillDays or RECENT_DAYS
            start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
            for a, b in spans(start, now):
                out.append((f'{station} hourly', queryUrl(station, a, b, HOURLY), HOURLY, station))
    return out


def runIngestion(db, fetch=None, backfillDays=0, monthly=False, now=None):
    """Returns (changes, failed, note). Each request is independent of the others' failure."""
    fetch = fetch or PacedFetcher()
    now = now or utcNow()
    changes, failures, notes = 0, [], []
    for name, url, resolution, station in plan(now, backfillDays, monthly):
        try:
            rows = parseCounts(fetch(url), station, resolution, now)
            changed = storeFeed(db, rows)
            changes += changed
            notes.append(f'{name} {len(rows)}')
            print(f'  {name}: {len(rows)} samples, {changed} changed')
        except Exception as error:
            failures.append(f'{name}: {type(error).__name__}: {error}')
            print(f'  {name}: ERROR {error} -- nothing stored from it')
    note = ', '.join(notes) + ('; FAILED ' + '; '.join(failures) if failures else '')
    return changes, bool(failures), note[:500]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Oulu neutron monitor ingestion')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--backfill', type=int, default=0, metavar='DAYS',
                       help='read this many days of hourly data instead of the last %d (once, for history)' % RECENT_DAYS)
    group.add_argument('--monthly', action='store_true', help='the whole monthly record since 1964 (once a month)')
    args = parser.parse_args(argv)
    db = openDb()
    job = JOB_MONTHLY if args.monthly else JOB
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Oulu neutron monitor ingestion ({job}) ===')
    with trackRun(db, job) as run:
        run.changes, run.failed, run.note = runIngestion(db, backfillDays=args.backfill, monthly=args.monthly)
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} changes')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
