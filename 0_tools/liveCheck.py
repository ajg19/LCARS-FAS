"""Read-only health check of the live LCARS-FAS site.

    python 0_tools/liveCheck.py                       # check LIVE
    python 0_tools/liveCheck.py --compare-assets      # ...and compare deployed frontend files with this working copy
    python 0_tools/liveCheck.py --quick               # skip the large downloads (active list, sky satellites)
    python 0_tools/liveCheck.py --base http://localhost:3000   # any other deployment

Makes only GET requests, the same as a visitor's browser, so it can never
change anything on the server. Standalone: Python standard library only,
3.9 or later.

THREE KINDS OF CHECK:
  endpoints   each main API endpoint answers 200 with JSON of the expected
              shape and a plausible size (CHECKS) -- catches a broken
              deploy, a failed restart, a missing or empty site file.
  freshness   the landing page's freshness table (api/status): every
              source's last run succeeded, and none is overdue -- its
              expected next sync is more than GRACE past. Catches a cron
              job that has stopped or keeps failing, or refused publishes.
              A source that has never run is a warning, not a failure:
              'Satellite groups' stays empty while CelesTrak is disabled.
  assets      (--compare-assets) the deployed frontend files match this
              working copy, ignoring line endings -- confirms a deploy
              carried what you meant it to.

Each check prints OK, WARN or FAIL, then a summary. Exit code: 0 when
nothing failed (1 with --strict if anything warned), 1 when anything
failed, 2 when the site couldn't be reached at all.
"""

import argparse
import gzip
import hashlib
import http.client
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT_BASE = 'https://gaps2024.com/LCARS-FAS'
USER_AGENT = 'LCARS-FAS liveCheck/1.0 (+https://github.com/ajg19/LCARS-FAS)'
TIMEOUT_SEC = 60
# How late a source's next sync may be before it counts as overdue: cron
# runs take minutes, and a run waits for the writers' lock.
GRACE = timedelta(hours=1)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = ('assets/lcars.js', 'assets/gsOpsPanel.js', 'assets/grdTrackPanel.js', 'assets/onOrbitPanel.js',
          'assets/grdViewPanel.js', 'assets/groundSegmentPanel.js', 'assets/bugReport.js', 'index.html')


# --- Shape checks: each returns None when fine, or what is wrong ---------------------------

def nonEmptyList(minItems, keys=()):
    def check(data):
        if not isinstance(data, list):
            return f'expected a list, got {type(data).__name__}'
        if len(data) < minItems:
            return f'only {len(data)} items (expected at least {minItems})'
        missing = [k for k in keys if k not in data[0]]
        return f'items lack {missing}' if missing else None
    return check


def dictWith(keys, listKey=None, minItems=1):
    def check(data):
        if not isinstance(data, dict):
            return f'expected an object, got {type(data).__name__}'
        missing = [k for k in keys if k not in data]
        if missing:
            return f'missing {missing}'
        if listKey and len(data[listKey]) < minItems:
            return f'{listKey} has {len(data[listKey])} items (expected at least {minItems})'
        return None
    return check


# (name, path, shape check, large download)
CHECKS = [
    ('landing page', '', None, False),
    ('freshness table', 'api/status', dictWith(('generatedUtc', 'sources'), 'sources', 5), False),
    ('news', 'api/news', nonEmptyList(10, ('title', 'url')), False),
    ('news topics', 'api/news/topic-counts', None, False),
    ('ground segment', 'api/ground-segment-assets', nonEmptyList(100, ('name', 'latitude', 'longitude')), False),
    ('sky catalogue', 'api/sky/catalogue', dictWith(('stars', 'lines', 'constellations'), 'stars', 1000), False),
    ('ISS details', 'api/sky/object?noradID=25544', dictWith(('noradID', 'name', 'perigee')), False),
    ('ON-ORBIT regimes', 'api/on-orbit/regimes', dictWith(('rows',), 'rows', 5), False),
    ('ON-ORBIT GEO belt', 'api/on-orbit/chart?name=geo-belt', dictWith(('rows', 'total'), 'rows', 1), False),
    ('ON-ORBIT owners', 'api/on-orbit/owners', dictWith(('rows',), 'rows', 10), False),
    ('launches per year', 'api/launches/per-year', dictWith(('rows',), 'rows', 50), False),
    ('ADD OBJ filters', 'api/orbital-objects/filter-options', dictWith(('owners', 'groups', 'launchSites'), 'groups', 5), False),
    ('ADD OBJ search', 'api/orbital-objects/search?group=starlink&limit=5', dictWith(('objects', 'truncated'), 'objects', 1), False),
    ('active satellites (GS OPS)', 'api/orbital-objects/active', nonEmptyList(10000, ('noradID', 'epoch', 'meanMotion')), True),
    ('sky satellites (GRD VIEW)', 'api/sky/satellites', nonEmptyList(1000), True),
]


class CutOff(Exception):
    """The response stopped before its declared length, twice."""


def fetch(base, path, attempts=2):
    """(status, body bytes, seconds). HTTP errors come back as a status; a
    download cut off part-way is retried once, then raises CutOff; a
    connection that can't be made at all raises URLError."""
    for attempt in range(attempts):
        try:
            return fetchOnce(base, path)
        except (http.client.IncompleteRead, ConnectionResetError) as error:
            reason = f'{type(error).__name__}: {str(error)[:80]}'
        except OSError as error:
            if isinstance(error, urllib.error.URLError):
                raise
            reason = f'{type(error).__name__}: {error}'
    raise CutOff(f'download cut off twice ({reason})')


def fetchOnce(base, path):
    url = base.rstrip('/') + '/' + path
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
            body = response.read()
            if response.headers.get('Content-Encoding') == 'gzip':
                body = gzip.decompress(body)
            return response.status, body, time.time() - started
    except urllib.error.HTTPError as error:
        return error.code, error.read(), time.time() - started


class Report:
    def __init__(self):
        self.counts = {'OK': 0, 'WARN': 0, 'FAIL': 0}

    def add(self, level, what, detail=''):
        self.counts[level] += 1
        print(f'  {level:4s}  {what}' + (f' -- {detail}' if detail else ''), flush=True)


# --- Checks -----------------------------------------------------------------------------

def checkEndpoints(base, report, quick):
    """Returns the parsed api/status payload, or None."""
    status = None
    for name, path, shape, large in CHECKS:
        if quick and large:
            continue
        label = f'{name} (/{path})'
        try:
            code, body, seconds = fetch(base, path)
        except CutOff as error:
            report.add('FAIL', label, str(error))
            continue
        if code != 200:
            report.add('FAIL', label, f'HTTP {code}')
            continue
        if shape is None:
            report.add('OK', label, f'{len(body):,} bytes, {seconds:.1f} s')
            continue
        try:
            data = json.loads(body)
        except ValueError:
            report.add('FAIL', label, 'not JSON')
            continue
        problem = shape(data)
        if problem:
            report.add('FAIL', label, problem)
        else:
            report.add('OK', label, f'{len(body):,} bytes, {seconds:.1f} s')
        if path == 'api/status':
            status = data
    return status


def parseUtc(text):
    return datetime.strptime(text[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)


def judgeFreshness(sources, now):
    """[(level, what, detail)] for each row of the freshness table."""
    results = []
    for row in sources:
        what = f"freshness: {row.get('data')}"
        last, next_ = row.get('lastRefreshUtc'), row.get('nextSyncUtc')
        if row.get('lastRunFailed'):
            results.append(('FAIL', what, f'last run FAILED (last success {last or "never"})'))
        elif not last:
            results.append(('WARN', what, 'never run (expected for Satellite groups while CelesTrak is disabled)'))
        elif next_ and now > parseUtc(next_) + GRACE:
            late = now - parseUtc(next_)
            results.append(('FAIL', what, f'overdue by {late.total_seconds() / 3600:.1f} h '
                                          f'(last refresh {last}, next sync was due {next_})'))
        else:
            age = (now - parseUtc(last)).total_seconds() / 3600
            results.append(('OK', what, f'refreshed {age:.1f} h ago, {row.get("changes")} changes'))
    return results


def checkFreshness(status, report, now=None):
    if status is None:
        report.add('FAIL', 'freshness', 'no freshness table to check')
        return
    for level, what, detail in judgeFreshness(status['sources'], now or datetime.now(timezone.utc)):
        report.add(level, what, detail)


def digest(data):
    return hashlib.md5(data.replace(b'\r\n', b'\n')).hexdigest()


def checkAssets(base, report):
    for path in ASSETS:
        local = os.path.join(REPO, path)
        if not os.path.exists(local):
            continue
        try:
            code, body, _ = fetch(base, '' if path == 'index.html' else path)
        except CutOff as error:
            report.add('FAIL', f'asset {path}', str(error))
            continue
        if code != 200:
            report.add('FAIL', f'asset {path}', f'HTTP {code}')
        elif digest(body) == digest(open(local, 'rb').read()):
            report.add('OK', f'asset {path}', 'matches this working copy')
        else:
            report.add('WARN', f'asset {path}', 'differs from this working copy (undeployed changes?)')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only health check of the live LCARS-FAS site.')
    parser.add_argument('--base', default=DEFAULT_BASE, help=f'site address (default {DEFAULT_BASE})')
    parser.add_argument('--quick', action='store_true', help='skip the large downloads')
    parser.add_argument('--compare-assets', action='store_true', help='compare deployed frontend files with this working copy')
    parser.add_argument('--strict', action='store_true', help='exit 1 on warnings too')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')

    print(f'=== LCARS-FAS live check: {args.base}  ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)')
    report = Report()
    try:
        print('endpoints:')
        status = checkEndpoints(args.base, report, args.quick)
        print('freshness:')
        checkFreshness(status, report)
        if args.compare_assets:
            print('assets:')
            checkAssets(args.base, report)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as error:
        print(f'  FAIL  site unreachable -- {error}')
        return 2
    c = report.counts
    verdict = 'FAIL' if c['FAIL'] else 'WARN' if c['WARN'] else 'OK'
    print(f'=== {verdict}: {c["OK"]} ok, {c["WARN"]} warnings, {c["FAIL"]} failures')
    return 1 if c['FAIL'] or (args.strict and c['WARN']) else 0


if __name__ == '__main__':
    sys.exit(main())
