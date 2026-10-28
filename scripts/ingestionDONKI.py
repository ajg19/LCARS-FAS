"""NASA DONKI ingestion: keeps databases/ingestionDONKI.db holding the
Space Weather Database Of Notifications, Knowledge, Information (NASA
CCMC, ccmc.gsfc.nasa.gov/DONKI): coronal mass ejections (CME),
high-speed streams (HSS), geomagnetic storms (GST), solar energetic
particle events (SEP), solar flares (FLR) and interplanetary shocks
(IPS).

Step 3 of 0_documentation/plans/spaceWeatherIngestionPlan.md. Fetches and
stores only; the publish step decides what reaches the website.

The API moved to ccmc.gsfc.nasa.gov on 30 Sep 2026 and needs no key (the
api.nasa.gov route is dead). CCMC's rules: real-time products are of
"prototyping quality"; acknowledge NASA CCMC / DONKI wherever shown.

One GET per event type for the last WINDOW_DAYS days (startDate and
endDate, gzip). Each event is stored whole, as the source's JSON, in
`events` (spaceWeatherSamples.py), keyed by (type, DONKI's own ID); an
event DONKI revises (versionId, new analyses) is a change, an unchanged
one is not. --backfill DAYS reads that many days instead, in stretches
of BACKFILL_CHUNK_DAYS, once, for history.

Each type is validated whole before anything from it is stored; a
surprise rejects that type and the run is recorded as failed. An empty
list is a quiet window, not a surprise.
"""

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

from dbPaths import DONKI_DB, dbPath
from ingestionLog import trackRun
from spaceWeatherSamples import FeedError, PacedFetcher, connect, loadJson, storeFeed, utcText

BASE_URL = 'https://ccmc.gsfc.nasa.gov/DONKI-API/get/'
JOB = 'donki'
WINDOW_DAYS = 7
BACKFILL_CHUNK_DAYS = 30

# event type -> (key holding DONKI's ID, key holding the start time)
TYPES = {
    'CME': ('activityID', 'startTime'),
    'HSS': ('hssID', 'eventTime'),
    'GST': ('gstID', 'startTime'),
    'SEP': ('sepID', 'eventTime'),
    'FLR': ('flrID', 'beginTime'),
    'IPS': ('activityID', 'eventTime'),
}


def openDb(path=None):
    return connect(path or dbPath(DONKI_DB))


def parseEvents(text, eventType):
    """-> event rows (type, startUtc, ID, record)."""
    idKey, timeKey = TYPES[eventType]
    data = loadJson(text)
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise FeedError(f'{eventType}: expected a list of objects')
    events = []
    for r in data:
        if not isinstance(r.get(idKey), str) or not r[idKey] or timeKey not in r:
            raise FeedError(f'{eventType}: record without {idKey} and {timeKey}')
        events.append((eventType, utcText(r[timeKey]), r[idKey], r))
    return events


def urlFor(eventType, start, end):
    return f'{BASE_URL}{eventType}?startDate={start:%Y-%m-%d}&endDate={end:%Y-%m-%d}'


def windows(days, today):
    """[(start, end)] covering the `days` days up to `today`, oldest first,
    in stretches of BACKFILL_CHUNK_DAYS."""
    start, spans = today - timedelta(days=days), []
    while start < today:
        stop = min(start + timedelta(days=BACKFILL_CHUNK_DAYS), today)
        spans.append((start, stop))
        start = stop
    return spans


def runIngestion(db, fetch=None, backfillDays=0, today=None):
    """Every event type for the rolling window (or the backfill). Each
    request is independent of the others' failure. Returns (changes,
    failed, note)."""
    fetch = fetch or PacedFetcher()
    today = today or datetime.now(timezone.utc).date()
    spans = windows(backfillDays, today) if backfillDays else [(today - timedelta(days=WINDOW_DAYS), today)]
    changes, failures, notes = 0, [], []
    for eventType in TYPES:
        count = 0
        for start, end in spans:
            try:
                events = parseEvents(fetch(urlFor(eventType, start, end)), eventType)
                changed = storeFeed(db, events=events)
                changes += changed
                count += len(events)
                print(f'  {eventType} {start}..{end}: {len(events)} events, {changed} changed')
            except Exception as error:
                failures.append(f'{eventType}: {type(error).__name__}: {error}')
                print(f'  {eventType} {start}..{end}: ERROR {error} -- nothing stored from it')
        notes.append(f'{eventType} {count}')
    note = ', '.join(notes) + ('; FAILED ' + '; '.join(failures) if failures else '')
    return changes, bool(failures), note[:500]


def main(argv=None):
    parser = argparse.ArgumentParser(description='NASA DONKI ingestion')
    parser.add_argument('--backfill', type=int, default=0, metavar='DAYS',
                        help='read this many days instead of the last %d (once, for history)' % WINDOW_DAYS)
    args = parser.parse_args(argv)
    db = openDb()
    print(f'\n=== [{time.strftime("%H:%M:%S")}] DONKI ingestion ===')
    with trackRun(db, JOB) as run:
        run.changes, run.failed, run.note = runIngestion(db, backfillDays=args.backfill)
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} changes')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
