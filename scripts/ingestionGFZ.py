"""GFZ Potsdam ingestion: keeps databases/ingestionGFZ.db holding the
official geomagnetic indices from the Geomagnetic Observatory Niemegk
(kp.gfz.de): Kp, ap, Ap, Hp30, Hp60, observed and adjusted F10.7, and the
international sunspot number.

Step 3 of 0_documentation/plans/spaceWeatherIngestionPlan.md. Fetches and
stores only; the publish step decides what reaches the website.

Licence: CC BY 4.0, except the sunspot numbers, which are CC BY-NC 4.0
(WDC-SILSO, Royal Observatory of Belgium). Cite:
  Matzka, J., Stolle, C., Yamazaki, Y., Bronkalla, O. and Morschhauser,
  A., 2021. The geomagnetic Kp index and derived indices of geomagnetic
  activity. Space Weather, https://doi.org/10.1029/2020SW002641
For ionospheric and atmospheric work GFZ recommends F10.7 observed
(gfzF107Obs), not adjusted.

Feeds (gzip, one GET each):
  nowcast  files/Kp_ap_Ap_SN_F107_nowcast.txt: the last 30 days, one line
           per UT day with eight Kp and ap values, Ap, SN, F10.7obs and
           F10.7adj. The newest values are nowcasts, replaced later by
           definitive ones. -1 means missing.
  api      json/?start=&end=&index=: one index per request. Hp30 and Hp60
           (half-hourly and hourly Hp, not in the nowcast file) come only
           from here. Timestamps are the START of the interval, as in the
           nowcast lines.

Every run reads the nowcast file and the last HP_DAYS days of Hp30 and
Hp60. --backfill DAYS also reads every index from the API for that many
days (one request per index per year, paced), once, for history.

Series (all `gfz...`): Kp, Ap3h (the 3-hourly ap), Hp30, Hp60; Ap (daily),
SunspotNumber, F107Obs, F107Adj (daily). Quality: 'pre' or 'def' (preliminary or
definitive) where GFZ says; a definitive value is never replaced by a
preliminary one. A value GFZ marks missing (-1) for a time that has begun
is stored as NULL; slots still in the future are skipped.

Each feed is validated whole before anything from it is stored; a surprise
rejects that feed and the run is recorded as failed.
"""

import argparse
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from dbPaths import GFZ_DB, dbPath
from ingestionLog import trackRun
from spaceWeatherSamples import FeedError, PacedFetcher, connect, loadJson, number, storeFeed, utcText

NOWCAST_URL = 'https://kp.gfz.de/app/files/Kp_ap_Ap_SN_F107_nowcast.txt'
API_URL = 'https://kp.gfz.de/app/json/?start={start}&end={end}&index={index}'
JOB = 'gfz'
HP_DAYS = 3
API_CHUNK_DAYS = 366

# API index -> (series, unit)
INDEXES = {
    'Kp': ('gfzKp', 'Kp'), 'ap': ('gfzAp3h', 'ap'), 'Ap': ('gfzAp', 'Ap'),
    'Hp30': ('gfzHp30', 'Hp'), 'Hp60': ('gfzHp60', 'Hp'),
    'SN': ('gfzSunspotNumber', 'count'), 'Fobs': ('gfzF107Obs', 'sfu'), 'Fadj': ('gfzF107Adj', 'sfu'),
}
RECENT_INDEXES = ('Hp30', 'Hp60')


def openDb(path=None):
    return connect(path or dbPath(GFZ_DB))


def utcNow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def reading(value, what, now, ts):
    """A float, or None where GFZ has -1 (missing). None again, without a
    row, for a slot that has not begun yet: returns (skip, value)."""
    value = number(value, what)
    missing = value is None or value == -1
    if missing and ts > stamp(now):
        return True, None
    return False, None if missing else value


# --- Nowcast file ---------------------------------------------------------------

NOWCAST_COLUMNS = 4 + 3 + 8 + 8 + 5   # YYYY MM DD days days_m Bsr dB Kp1-8 ap1-8 Ap SN F10.7obs F10.7adj D


def parseNowcast(text, now=None):
    """-> sample rows. Reads the '#' header only as far as the title."""
    now = now or utcNow()
    if 'geomagnetic planetary three-hour index Kp' not in text[:600]:
        raise FeedError('nowcast: unexpected header')
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != NOWCAST_COLUMNS or not re.fullmatch(r'\d{4}', parts[0]):
            raise FeedError(f'nowcast: unexpected line {line!r}')
        try:
            day = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
            values = [float(p) for p in parts[3:]]
            flag = int(parts[-1])
        except ValueError:
            raise FeedError(f'nowcast: unreadable line {line!r}')
        if flag not in (0, 1, 2):
            raise FeedError(f'nowcast: unexpected D flag in {line!r}')
        kp, ap = values[4:12], values[12:20]
        dailyAp, sn, fobs, fadj = values[20:24]
        kpQuality = 'def' if flag >= 1 else 'pre'
        snQuality = 'def' if flag == 2 else 'pre'
        daily = ((('gfzAp', 'Ap', dailyAp, kpQuality), ('gfzSunspotNumber', 'count', sn, snQuality),
                  ('gfzF107Obs', 'sfu', fobs, None), ('gfzF107Adj', 'sfu', fadj, None)))
        for series, unit, value, quality in daily:
            ts = stamp(day)
            skip, value = reading(value, series, now, ts)
            if not skip:
                rows.append((series, ts, value, unit, quality))
        for i in range(8):
            ts = stamp(day + timedelta(hours=3 * i))
            for series, unit, raw in (('gfzKp', 'Kp', kp[i]), ('gfzAp3h', 'ap', ap[i])):
                skip, value = reading(raw, series, now, ts)
                if not skip:
                    rows.append((series, ts, value, unit, kpQuality))
    if not rows:
        raise FeedError('nowcast: no data lines')
    return rows


# --- JSON API -------------------------------------------------------------------

def parseApi(text, index, now=None):
    """-> sample rows for one index. The response is an object with
    'datetime', the index's own list, and optionally a 'status' (or
    '<index>status') list of 'pre' / 'def'."""
    now = now or utcNow()
    data = loadJson(text)
    if index not in INDEXES:
        raise FeedError(f'api: unknown index {index!r}')
    series, unit = INDEXES[index]
    if not isinstance(data, dict):
        raise FeedError(f'{index}: expected an object')
    times, values = data.get('datetime'), data.get(index)
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values):
        raise FeedError(f'{index}: datetime and {index} must be lists of equal length')
    statuses = data.get('status', data.get(index + 'status'))
    if statuses is not None and (not isinstance(statuses, list) or len(statuses) != len(times)):
        raise FeedError(f'{index}: status list does not match')
    rows = []
    for i, (when, raw) in enumerate(zip(times, values)):
        ts = utcText(when)
        quality = statuses[i] if statuses else None
        if quality not in (None, 'pre', 'def'):
            raise FeedError(f'{index}: unexpected status {quality!r}')
        skip, value = reading(raw, index, now, ts)
        if not skip:
            rows.append((series, ts, value, unit, quality))
    return rows


def apiUrls(index, start, end):
    """One URL per API_CHUNK_DAYS-day stretch from start to end (datetimes)."""
    urls = []
    while start < end:
        stop = min(start + timedelta(days=API_CHUNK_DAYS), end)
        urls.append(API_URL.format(start=stamp(start), end=stamp(stop), index=index))
        start = stop
    return urls


# --- Run ----------------------------------------------------------------------

def runIngestion(db, fetch=None, backfillDays=0, now=None):
    """The nowcast file, Hp30 and Hp60 for the last HP_DAYS days and, with
    backfillDays, every index for that many days. Each request is its own
    feed, independent of the others' failure. Returns (changes, failed,
    note)."""
    fetch = fetch or PacedFetcher()
    now = now or utcNow()
    hour = now.replace(minute=0, second=0, microsecond=0)
    plan = [('nowcast', NOWCAST_URL, lambda text: parseNowcast(text, now))]
    for index in RECENT_INDEXES:
        for url in apiUrls(index, hour - timedelta(days=HP_DAYS), hour):
            plan.append((index, url, lambda text, index=index: parseApi(text, index, now)))
    if backfillDays:
        for index in INDEXES:
            for url in apiUrls(index, hour - timedelta(days=backfillDays), hour):
                plan.append((f'{index} backfill', url, lambda text, index=index: parseApi(text, index, now)))
    changes, failures, notes = 0, [], []
    for name, url, parse in plan:
        try:
            rows = parse(fetch(url))
            changed = storeFeed(db, rows, finalQuality='def')
            changes += changed
            notes.append(f'{name} {len(rows)}')
            print(f'  {name}: {len(rows)} samples, {changed} changed')
        except Exception as error:
            failures.append(f'{name}: {type(error).__name__}: {error}')
            print(f'  {name}: ERROR {error} -- nothing stored from it')
    note = ', '.join(notes) + ('; FAILED ' + '; '.join(failures) if failures else '')
    return changes, bool(failures), note[:500]


def main(argv=None):
    parser = argparse.ArgumentParser(description='GFZ Potsdam index ingestion')
    parser.add_argument('--backfill', type=int, default=0, metavar='DAYS',
                        help='also read every index from the API for this many days (once, for history)')
    args = parser.parse_args(argv)
    db = openDb()
    print(f'\n=== [{time.strftime("%H:%M:%S")}] GFZ ingestion ===')
    with trackRun(db, JOB) as run:
        run.changes, run.failed, run.note = runIngestion(db, backfillDays=args.backfill)
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} changes')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
