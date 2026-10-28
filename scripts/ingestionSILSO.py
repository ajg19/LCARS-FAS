"""SILSO sunspot number ingestion: keeps databases/ingestionSILSO.db holding the
monthly mean total sunspot number (version 2.0, since 1749) from WDC-SILSO,
Royal Observatory of Belgium, Brussels.

For the solar cycle chart S7 and the GCR cycle chart G3
(0_documentation/plans/spaceWeatherChartsPlan.md). Fetches and stores only.

Licence and credit: CC BY-NC 4.0. Credit: "Source: WDC-SILSO, Royal Observatory
of Belgium, Brussels" (https://sidc.be/SILSO/citations, DOI
10.24414/qnza-ac80 on https://sidc.be/SILSO/datafiles). Give the licence link
and say if the data were changed.

Feed: https://www.sidc.be/SILSO/DATA/SN_m_tot_V2.0.csv, semicolon-separated:
  year; month; decimal year; monthly mean; standard deviation; observations;
  definitive marker (1 = definitive, 0 = provisional)
A standard deviation of -1 and observations of -1 mean "not available" (the
early record). About 125 KB; the file changes about once a month. Before
downloading, a HEAD request compares Last-Modified with the one stored in
sourceFiles; an unchanged file is not downloaded again.

Series (time stamp = first day of the month, UTC):
  silsoMonthlyMean   monthly mean sunspot number ('count')
  silsoMonthlyStd    standard deviation of the daily values
  silsoMonthlyObs    number of daily observations used ('count')
Quality: 'definitive' or 'provisional'. A definitive value is never replaced by a
provisional one; a provisional one is replaced when SILSO makes it definitive
(the definitive record lags by about a quarter).
"""

import argparse
import sys
import time
import urllib.request
from datetime import datetime, timezone

from common import USER_AGENT
from dbPaths import SILSO_DB, dbPath
from ingestionLog import trackRun
from spaceWeatherSamples import FeedError, PacedFetcher, connect, number, storeFeed

URL = 'https://www.sidc.be/SILSO/DATA/SN_m_tot_V2.0.csv'
JOB = 'silso'
MIN_ROWS = 3000       # the record has about 3,330 months; a much shorter file is cut off
FIRST_MONTH = (1749, 1)


def openDb(path=None):
    db = connect(path or dbPath(SILSO_DB))
    db.execute('CREATE TABLE IF NOT EXISTS sourceFiles (url TEXT PRIMARY KEY, lastModified TEXT, '
               'fetchedAt TEXT) WITHOUT ROWID')
    db.commit()
    return db


def parseMonthly(text):
    rows = []
    previous = None
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(';')]
        if len(parts) != 7:
            raise FeedError(f'silso: unexpected line {line!r}')
        try:
            year, month, flag = int(parts[0]), int(parts[1]), int(parts[6])
        except ValueError:
            raise FeedError(f'silso: unreadable line {line!r}')
        if not (1749 <= year <= 2200 and 1 <= month <= 12) or flag not in (0, 1) or (year, month) <= (previous or (0, 0)):
            raise FeedError(f'silso: unexpected month, order or marker in {line!r}')
        previous = (year, month)
        mean = number(parts[3], 'silso mean', allowText=True)
        if mean is None or mean < 0:
            raise FeedError(f'silso: no monthly mean in {line!r}')
        std, obs = (None if v in (None, -1.0) else v for v in (number(parts[4], 'silso std', allowText=True),
                                                              number(parts[5], 'silso obs', allowText=True)))
        ts = f'{year:04d}-{month:02d}-01T00:00:00Z'
        quality = 'definitive' if flag else 'provisional'
        rows += [('silsoMonthlyMean', ts, mean, 'count', quality), ('silsoMonthlyStd', ts, std, 'count', quality),
                 ('silsoMonthlyObs', ts, obs, 'count', quality)]
    if len(rows) < 3 * MIN_ROWS:
        raise FeedError(f'silso: only {len(rows) // 3} months; expected about 3,300')
    return rows


def headLastModified(url=URL):
    """The Last-Modified header of the file (one HEAD request), or None."""
    request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.headers.get('Last-Modified')


def runIngestion(db, fetch=None, head=headLastModified, force=False):
    """Returns (changes, failed, note). Does nothing, with no download, when the file's
    Last-Modified is the one already stored."""
    stored = db.execute('SELECT lastModified FROM sourceFiles WHERE url = ?', (URL,)).fetchone()
    try:
        modified = head()
    except Exception as error:
        modified = None
        print(f'  HEAD failed ({error}); fetching anyway')
    if not force and modified and stored and stored[0] == modified:
        print(f'  unchanged since {modified}; nothing fetched')
        return 0, False, f'unchanged ({modified})'
    try:
        rows = parseMonthly((fetch or PacedFetcher())(URL))
        changed = storeFeed(db, rows, finalQuality='definitive')
    except Exception as error:
        print(f'  ERROR {error} -- nothing stored')
        return 0, True, f'{type(error).__name__}: {error}'[:500]
    with db:
        db.execute('INSERT OR REPLACE INTO sourceFiles (url, lastModified, fetchedAt) VALUES (?, ?, ?)',
                   (URL, modified, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))
    print(f'  {len(rows) // 3} months, {changed} changed')
    return changed, False, f'{len(rows) // 3} months; last-modified {modified}'


def main(argv=None):
    parser = argparse.ArgumentParser(description='SILSO monthly sunspot number ingestion')
    parser.add_argument('--force', action='store_true', help='download even if Last-Modified is unchanged')
    args = parser.parse_args(argv)
    db = openDb()
    print(f'\n=== [{time.strftime("%H:%M:%S")}] SILSO ingestion ===')
    with trackRun(db, JOB) as run:
        run.changes, run.failed, run.note = runIngestion(db, force=args.force)
    print(f'  {"FAILED" if run.failed else "OK"} -- {run.note}; {run.changes} changes')
    db.close()
    return 1 if run.failed else 0


if __name__ == '__main__':
    sys.exit(main())
