"""Read-only health check of the live LCARS-FAS site.

    python 0_tools/liveCheck.py                       # check LIVE
    python 0_tools/liveCheck.py --compare-assets      # ...and compare deployed frontend files with this working copy
    python 0_tools/liveCheck.py --quick               # skip the large downloads (active list, sky satellites)
    python 0_tools/liveCheck.py --base http://localhost:3000   # any other deployment

Makes only GET requests, the same as a visitor's browser (including the
Accept-Encoding: gzip every browser sends), so it can never change
anything on the server. Standalone: Python standard library only, 3.9+.
Requests are spaced a random DELAY_RANGE_SEC apart: a burst of scripted requests trips
the host's bot protection, which then answers with a "please wait while
your request is being verified" page -- recognised and reported as
"not checked", never as a pass or a failure.

FOUR KINDS OF CHECK:
  pages & APIs  each main endpoint answers 200 with JSON of the expected
                shape and a plausible size (CHECKS) -- catches a broken
                deploy, a failed restart, a missing or empty site file.
  freshness     the landing page's freshness table (api/status): every
                source's last run succeeded and none is overdue (more than
                GRACE past its expected next sync) -- catches a stopped or
                failing cron job, or refused publishes. A source that never
                ran is a warning ('Satellite groups' while CelesTrak is
                disabled).
  privacy       files that must never be public (PRIVATE) are refused by
                the web server (the .htaccess block list): databases,
                credentials, code, temporary files. Only the first 1 KB of
                each is requested, so an exposed database isn't downloaded.
  assets        (--compare-assets) the deployed frontend files match this
                working copy, ignoring line endings.

Every line reads on its own: OK / WARN / FAIL, what was checked, what was
found. Exit code: 0 when nothing failed (1 with --strict if anything
warned), 1 when anything failed, 2 when the site couldn't be reached.
"""

import argparse
import gzip
import hashlib
import http.client
import json
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT_BASE = 'https://gaps2024.com/LCARS-FAS'
USER_AGENT = 'LCARS-FAS liveCheck/1.1 (+https://github.com/ajg19/LCARS-FAS)'
TIMEOUT_SEC = 60
# Human pace, with random variation between requests: regular or rapid
# bursts trip the host's bot screening.
DELAY_RANGE_SEC = (1.5, 4.5)
# How late a source's next sync may be before it counts as overdue: cron
# runs take minutes, and a run waits for the writers' lock.
GRACE = timedelta(hours=1)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = ('assets/lcars.js', 'assets/gsOpsPanel.js', 'assets/grdTrackPanel.js', 'assets/onOrbitPanel.js',
          'assets/grdViewPanel.js', 'assets/groundSegmentPanel.js', 'assets/bugReport.js', 'index.html')
BOT_CHECK_MARKER = b'being verified'


# --- Shape checks: each returns (problem or None, item count or None) ------------------------

def nonEmptyList(minItems, keys=()):
    def check(data):
        if not isinstance(data, list):
            return f'expected a list, got {type(data).__name__}', None
        if len(data) < minItems:
            return f'only {len(data)} items, expected at least {minItems}', len(data)
        missing = [k for k in keys if k not in data[0]]
        return (f'items lack {", ".join(missing)}' if missing else None), len(data)
    return check


def dictWith(keys, listKey=None, minItems=1):
    def check(data):
        if not isinstance(data, dict):
            return f'expected an object, got {type(data).__name__}', None
        missing = [k for k in keys if k not in data]
        if missing:
            return f'missing {", ".join(missing)}', None
        count = len(data[listKey]) if listKey else None
        if listKey and count < minItems:
            return f'{listKey} has only {count} items, expected at least {minItems}', count
        return None, count
    return check


# (what it is, path, shape check, what a counted item is, large download)
CHECKS = [
    ('Landing page', '', None, None, False),
    ('Freshness table', 'api/status', dictWith(('generatedUtc', 'sources'), 'sources', 5), 'sources', False),
    ('News list', 'api/news', nonEmptyList(10, ('title', 'url')), 'articles', False),
    ('News topic counts', 'api/news/topic-counts', None, None, False),
    ('Ground segment map', 'api/ground-segment-assets', nonEmptyList(100, ('name', 'latitude', 'longitude')), 'sites', False),
    ('GRD VIEW star map', 'api/sky/catalogue', dictWith(('stars', 'lines', 'constellations'), 'stars', 1000), 'stars', False),
    ('Satellite details (ISS)', 'api/sky/object?noradID=25544', dictWith(('noradID', 'name', 'perigee')), None, False),
    ('ON-ORBIT regimes chart', 'api/on-orbit/regimes', dictWith(('rows',), 'rows', 5), 'regimes', False),
    ('ON-ORBIT GEO belt chart', 'api/on-orbit/chart?name=geo-belt', dictWith(('rows', 'total'), 'rows', 1), 'rows', False),
    ('ON-ORBIT owners chart', 'api/on-orbit/owners', dictWith(('rows',), 'rows', 10), 'owners', False),
    ('LAUNCHES per-year chart', 'api/launches/per-year', dictWith(('rows',), 'rows', 50), 'years', False),
    ('ADD OBJ filter lists', 'api/orbital-objects/filter-options', dictWith(('owners', 'groups', 'launchSites'), 'groups', 5), 'groups', False),
    ('ADD OBJ search', 'api/orbital-objects/search?group=starlink&limit=5', dictWith(('objects', 'truncated'), 'objects', 1), 'objects', False),
    ('GS OPS satellite list', 'api/orbital-objects/active', nonEmptyList(10000, ('noradID', 'epoch', 'meanMotion')), 'satellites', True),
    ('GRD VIEW satellites', 'api/sky/satellites', nonEmptyList(1000), 'satellites', True),
]

# Files the web server must refuse: (path, what it is). Covers each kind
# of file the .htaccess block list protects -- folders, extensions, dot-files.
PRIVATE = [
    ('databases/siteOrbital.db', 'site database'),
    ('databases/siteOrbital.db.prev', 'previous site database'),
    ('databases/siteOrbital.db.tmp', 'publish temporary file'),
    ('databases/.writers.lock', 'writers lock file'),
    ('databases/ingestionSpaceTrack.db', 'Space-Track data'),
    ('databases/inboxBugReports.db', 'visitor bug reports'),
    ('ingestionDBs/gcat.db', 'old database folder'),
    ('spacetrack.env', 'Space-Track credentials'),
    ('.env', 'server settings'),
    ('server.py', 'server code'),
    ('scripts/dbPaths.py', 'pipeline code'),
    ('setupCron.sh', 'cron installer'),
    ('tmp/restart.txt', 'restart trigger'),
    ('.git/config', 'git configuration'),
    ('.referenceUpload/ingestionGroundSegment.db', 'deploy upload folder'),
]


class CutOff(Exception):
    """The response stopped before its declared length, twice."""


def fetchOnce(base, path, extraHeaders=None, limit=None):
    url = base.rstrip('/') + '/' + path
    headers = {'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip', **(extraHeaders or {})}
    request = urllib.request.Request(url, headers=headers)
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
            body = response.read(limit) if limit else response.read()
            if not limit and response.headers.get('Content-Encoding') == 'gzip':
                body = gzip.decompress(body)
            return response.status, body, time.time() - started
    except urllib.error.HTTPError as error:
        return error.code, error.read(limit) if limit else error.read(), time.time() - started


def fetch(base, path, extraHeaders=None, attempts=2, limit=None):
    """(status, body, seconds). HTTP errors come back as a status; a
    download cut off part-way is retried once, then raises CutOff; a site
    that can't be reached at all raises URLError."""
    time.sleep(random.uniform(*DELAY_RANGE_SEC))
    for _ in range(attempts):
        try:
            return fetchOnce(base, path, extraHeaders, limit)
        except (http.client.IncompleteRead, ConnectionResetError) as error:
            reason = type(error).__name__
        except OSError as error:
            if isinstance(error, urllib.error.URLError):
                raise
            reason = f'{type(error).__name__}: {error}'
    raise CutOff(reason)


def isBotCheck(body):
    return BOT_CHECK_MARKER in body[:20000]


def size(n):
    return f'{n / 1e6:.1f} MB' if n >= 1e6 else f'{n / 1e3:.0f} KB' if n >= 1e3 else f'{n} B'


class Report:
    def __init__(self):
        self.counts = {'OK': 0, 'WARN': 0, 'FAIL': 0}

    def add(self, level, text):
        self.counts[level] += 1
        print(f'  {level:4s}  {text}', flush=True)


# --- Checks -----------------------------------------------------------------------------

def checkEndpoints(base, report, quick):
    """Returns the parsed api/status payload, or None."""
    status = None
    for name, path, shape, unit, large in CHECKS:
        if quick and large:
            continue
        where = f'/{path}'
        try:
            code, body, seconds = fetch(base, path)
        except CutOff as error:
            report.add('FAIL', f'{name} incomplete: download cut off twice ({error}) at {where}')
            continue
        if code == 200 and isBotCheck(body):
            report.add('WARN', f"{name} not checked: the host's bot check answered instead (too many requests? retry later)")
            continue
        if code != 200:
            report.add('FAIL', f'{name} broken: HTTP {code} at {where}')
            continue
        if shape is None:
            report.add('OK', f'{name} works ({size(len(body))}, {seconds:.1f} s)')
            continue
        try:
            data = json.loads(body)
        except ValueError:
            report.add('FAIL', f"{name} broken: reply isn't JSON at {where}")
            continue
        problem, count = shape(data)
        if problem:
            report.add('FAIL', f'{name} wrong: {problem} at {where}')
        else:
            counted = f'{count:,} {unit}, ' if count is not None and unit else ''
            report.add('OK', f'{name} works ({counted}{size(len(body))}, {seconds:.1f} s)')
        if path == 'api/status':
            status = data
    return status


def parseUtc(text):
    return datetime.strptime(text[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)


def hours(delta):
    h = delta.total_seconds() / 3600
    return f'{h * 60:.0f} min' if h < 1 else f'{h:.1f} h' if h < 48 else f'{h / 24:.1f} days'


def judgeFreshness(sources, now):
    """[(level, text)] for each row of the freshness table."""
    results = []
    for row in sources:
        name = row.get('data')
        last, next_ = row.get('lastRefreshUtc'), row.get('nextSyncUtc')
        if row.get('lastRunFailed'):
            since = f'site still shows data from {last[:16]}Z' if last else 'no successful run ever'
            results.append(('FAIL', f'{name} refresh failing: its last run failed; {since}'))
        elif not last:
            results.append(('WARN', f'{name} never refreshed: no run recorded '
                                    '(normal for Satellite groups while CelesTrak is disabled)'))
        elif next_ and now > parseUtc(next_) + GRACE:
            results.append(('FAIL', f'{name} stale: refresh {hours(now - parseUtc(next_))} overdue '
                                    f'(was due {next_[11:16]}Z) -- is its cron job running?'))
        else:
            due = f', next due {next_[11:16]}Z' if next_ else ''
            results.append(('OK', f'{name} up to date: refreshed {hours(now - parseUtc(last))} ago{due}'))
    return results


def checkFreshness(status, report, now=None):
    if status is None:
        report.add('FAIL', 'Freshness not checked: the freshness table itself failed (see above)')
        return
    for level, text in judgeFreshness(status['sources'], now or datetime.now(timezone.utc)):
        report.add(level, text)


def looksLikeHtml(body):
    return body.lstrip()[:15].lower().startswith((b'<!doctype html', b'<html'))


def judgeExposure(path, what, code, body):
    """(level, text) for one private path's response. None of the private
    files is HTML, so an HTML reply is a bot-check or error page standing
    in for it -- not checked, rather than exposed (the bot-check marker
    itself may lie beyond the first 1 KB read)."""
    if code in (403, 404):
        return 'OK', f'{what} not public (/{path} refused, {code})'
    if code in (200, 206) and (isBotCheck(body) or looksLikeHtml(body)):
        return 'WARN', f"{what} not checked: an HTML page (the host's bot check?) answered at /{path}; retry later"
    if code in (200, 206):
        return 'FAIL', f'{what} EXPOSED: /{path} can be downloaded -- add it to the .htaccess block list'
    return 'WARN', f'{what} unclear: /{path} answered HTTP {code}, expected 403 or 404'


def checkPrivacy(base, report):
    for path, what in PRIVATE:
        try:
            code, body, _ = fetch(base, path, {'Range': 'bytes=0-1023', 'Accept-Encoding': 'identity'}, limit=1024)
        except CutOff as error:
            report.add('WARN', f'{what} not checked: request cut off ({error}) at /{path}')
            continue
        report.add(*judgeExposure(path, what, code, body))


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
            report.add('FAIL', f'{path} not checked: download cut off twice ({error})')
            continue
        if code == 200 and isBotCheck(body):
            report.add('WARN', f"{path} not checked: the host's bot check answered instead")
        elif code != 200:
            report.add('FAIL', f'{path} missing on the site: HTTP {code}')
        elif digest(body) == digest(open(local, 'rb').read()):
            report.add('OK', f'{path} deployed copy matches this working copy')
        else:
            report.add('WARN', f'{path} deployed copy differs from this working copy (changes not yet deployed?)')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only health check of the live LCARS-FAS site.')
    parser.add_argument('--base', default=DEFAULT_BASE, help=f'site address (default {DEFAULT_BASE})')
    parser.add_argument('--quick', action='store_true', help='skip the large downloads')
    parser.add_argument('--compare-assets', action='store_true', help='compare deployed frontend files with this working copy')
    parser.add_argument('--strict', action='store_true', help='exit 1 on warnings too')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')

    print(f'=== LCARS-FAS live check of {args.base} at {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z')
    report = Report()
    try:
        print('Pages and APIs (does each answer correctly?):')
        status = checkEndpoints(args.base, report, args.quick)
        print('Freshness (is every data source being refreshed on schedule?):')
        checkFreshness(status, report)
        print('Privacy (are private files refused by the web server?):')
        checkPrivacy(args.base, report)
        if args.compare_assets:
            print('Assets (is what you deployed what you have locally?):')
            checkAssets(args.base, report)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as error:
        print(f'  FAIL  Site unreachable: {error}')
        return 2
    c = report.counts
    total = sum(c.values())
    if c['FAIL']:
        verdict = f"FAIL -- {c['FAIL']} problem(s) need attention"
    elif c['WARN']:
        verdict = f"OK with {c['WARN']} warning(s)"
    else:
        verdict = 'OK -- everything checked out'
    print(f"=== RESULT: {verdict} ({total} checks: {c['OK']} OK, {c['WARN']} warnings, {c['FAIL']} failures)")
    return 1 if c['FAIL'] or (args.strict and c['WARN']) else 0


if __name__ == '__main__':
    sys.exit(main())
