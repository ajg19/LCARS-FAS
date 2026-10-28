"""Tickbox front end for the LCARS-FAS tests: pick tests in a table, run them, see the results.

    python 0_tools/testHarness.py

The table groups everything by where it shows up: the sections of the
LCARS spine, the server-side backend, and deployment. Columns:
Functionality (spine section or backend area), what is tested, and a
tickbox. Click a tickbox to tick or untick it. Ticking a heading ticks
everything under it; expand a row (the arrow) to pick single tests.

Two kinds of row:
  code tests   the pytest suite in 0_tests/, run on this laptop. It never
               touches a server or the real databases.
  site checks  0_tools/checkLiveDeployment.py's checks, which are GET
               requests to a running site: pages and APIs, data
               freshness, privacy (the .htaccess block list), deployed
               files.

The ENVIRONMENT toggle at the top picks the target:
  DEV / LOCAL     code tests, plus site checks against the local server
                  (python server.py, http://localhost:3000), at full speed.
  LIVE / GODADDY  site checks only, against https://gaps2024.com/LCARS-FAS,
                  spaced at human pace. Code tests are greyed out, since
                  they don't test the live site.

PACE sets the pause between requests to a site, with random variation (a
steady or rapid rhythm trips the host's bot screening). Fast (no pause) is
for the local server only; LIVE offers Normal, Careful and Very careful, and
never goes quicker than 1.5 s between requests.

PRIVATE-FILE PROBES (the privacy rows: .env, spacetrack.env, server.py,
databases, .git...) are locked. They are greyed out until you tick "Allow
probes of private files", and the lock closes again after every run and at
every start. Ask for them only after a deploy or an .htaccess change:
scanners request exactly these paths, so a bot screen may take notice.

After a run, rows turn green (passed), amber (warning, skipped or not
checked) or red (failed); "Tick failed" re-selects just the failures.
The tests are found afresh at every start, and a test with no row in UNITS
is listed under "Unassigned tests", so none is ever hidden. Your
environment and ticks are remembered in ~/.lcarsFasTestHarness.json.

Standard library only (tkinter), on Windows and Linux. On Linux, tkinter
may be a separate package: sudo apt install python3-tk.
"""

import ast
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = '0_tests'
sys.path.insert(0, os.path.join(REPO, '0_tools'))
import checkLiveDeployment as cld  # noqa: E402

ENVIRONMENTS = {
    'DEV': {'label': 'DEV / LOCAL', 'base': 'http://127.0.0.1:3000', 'colour': '#2e7d32',
            'note': 'Code tests run on this laptop. Site checks go to the local server '
                    '(start it with: python server.py).'},
    'LIVE': {'label': 'LIVE / GODADDY', 'base': cld.DEFAULT_BASE, 'colour': '#c62828',
             'note': f'Site checks go to {cld.DEFAULT_BASE}, read-only, at human pace. '
                     'Code tests are greyed out: they test this laptop\'s code, not the live site.'},
}
# Pause between requests, seconds (low, high); the actual gap is random in between.
PACES = {'Fast (no pause)': (0, 0), 'Normal (1.5-4.5 s)': (1.5, 4.5), 'Careful (4-10 s)': (4, 10),
         'Very careful (8-20 s)': (8, 20)}
PACES_BY_ENV = {'DEV': list(PACES), 'LIVE': list(PACES)[1:]}
DEFAULT_PACE = {'DEV': 'Fast (no pause)', 'LIVE': 'Careful (4-10 s)'}
LIVE_MIN_DELAY = 1.5
PROBE_PREFIX = 'privacy:'
SETTINGS = os.path.join(os.path.expanduser('~'), '.lcarsFasTestHarness.json')

SPINE, BACKEND, DEPLOYMENT = 'LCARS SPINE', 'SERVER-SIDE BACKEND', 'DEPLOYMENT'

# Each row of the table: (heading, functionality, what is tested, kind, contents).
#   kind 'code': contents are (test file, test-name prefixes, or None for the whole file).
#   kind 'site': contents are site-check ids: 'endpoint:<name in cld.CHECKS>',
#                'freshness', 'privacy' (every cld.PRIVATE path), 'assets' (every cld.ASSETS file).
#   kind 'none': no tests yet.
# A test goes in the first row that matches it.
UNITS = [
    (SPINE, 'LANDING PAGE', 'Freshness table API (api/status): reply shape; next sync = last start + interval; '
                            'newest of several job names wins', 'code',
     [('test_server.py', ('test_status_',))]),
    (SPINE, 'LANDING PAGE', 'Landing page loads; freshness table answers with at least 5 data sources', 'site',
     ['endpoint:Landing page', 'endpoint:Freshness table']),
    (SPINE, 'NEWS', 'News API: article list, limit and topic filters, unknown topic gives an empty list, '
                    'SQL-injection safety, topic counts', 'code',
     [('test_server.py', ('test_news_',))]),
    (SPINE, 'NEWS', 'News list (10+ articles with title and link) and topic counts answer', 'site',
     ['endpoint:News list', 'endpoint:News topic counts']),
    (SPINE, 'GRD-TRACK · ADD OBJ', 'Object lookup by catalogue number (empty and malformed IDs), filter lists, search by '
                                   'altitude regime, inclination band and name, SQL-injection safety', 'code',
     [('test_server.py', ('test_orbital_objects_', 'test_filter_options_'))]),
    (SPINE, 'GRD-TRACK · ADD OBJ', 'Filter lists (owners, groups, launch sites) and a Starlink group search answer', 'site',
     ['endpoint:ADD OBJ filter lists', 'endpoint:ADD OBJ search']),
    (SPINE, 'ON-ORBIT', 'Chart APIs: every chart answers, reply shapes, SpaceX and other filters honoured '
                        '(bad values fall back), unknown chart gives 404', 'code',
     [('test_server.py', ('test_on_orbit_',))]),
    (SPINE, 'ON-ORBIT', 'Precomputed overview figures (orbitStats.py): regimes, owners, GEO belt, debris and the '
                        'other chart tables, from stand-in data', 'code',
     [('test_orbitStats.py', None)]),
    (SPINE, 'ON-ORBIT', 'Regimes, GEO-belt and owners charts answer with plausible row counts', 'site',
     ['endpoint:ON-ORBIT regimes chart', 'endpoint:ON-ORBIT GEO belt chart', 'endpoint:ON-ORBIT owners chart']),
    (SPINE, 'GS OPS', 'Link budget: EIRP class tier, and its GCAT fallback when CelesTrak groups are unavailable', 'code',
     [('test_enrichEirp.py', None)]),
    (SPINE, 'GS OPS', 'Link budget: each satellite\'s main downlink and uplink chosen from its SatNOGS transmitters', 'code',
     [('test_rfSelection.py', None)]),
    (SPINE, 'GS OPS', 'Satellite list for the pass predictions (10,000+ objects; a large download)', 'site',
     ['endpoint:GS OPS satellite list']),
    (SPINE, 'GRD VIEW', 'Sky APIs: star catalogue (stars, constellation lines), browser caching with 304, '
                        'object lookup refuses bad and unknown IDs', 'code',
     [('test_server.py', ('test_sky_',))]),
    (SPINE, 'GRD VIEW', 'Satellite brightness (standard magnitudes): stations, Starlink generations, size from GCAT, '
                        'defaults', 'code',
     [('test_estimateBrightness.py', None)]),
    (SPINE, 'GRD VIEW', 'Star map, satellite list (a large download) and one satellite\'s details (ISS) answer', 'site',
     ['endpoint:GRD VIEW star map', 'endpoint:GRD VIEW satellites', 'endpoint:Satellite details (ISS)']),
    (SPINE, 'LAUNCHES', 'Launch chart APIs: per year, by country (adds up to the yearly total), payloads and '
                        're-entries, SpaceX and outcome filters', 'code',
     [('test_server.py', ('test_launch',))]),
    (SPINE, 'LAUNCHES', 'Launches-per-year chart answers with 50+ years', 'site',
     ['endpoint:LAUNCHES per-year chart']),
    (SPINE, 'GRND SGMNT', 'Ground-segment sites API returns a list', 'code',
     [('test_server.py', ('test_ground_segment_',))]),
    (SPINE, 'GRND SGMNT', 'Ground-segment map data answers with 100+ sites with coordinates', 'site',
     ['endpoint:Ground segment map']),
    (SPINE, 'ORGANISATIONS', 'No automated tests yet', 'none', []),
    (SPINE, 'WEATHER', 'Weather APIs (now, series, events, map, value at any latitude and longitude): native and hourly series, bad input refused (400), '
                       'unknown names (404), no weather file (503), gzip and 304; the freshness rows', 'code',
     [('test_serverWeather.py', None)]),
    (SPINE, 'WEATHER', 'TEC APIs (index, CODE map by day and hour, latest GloTEC refreshed on demand with one fetch at a time and a '
                       'stale fallback, TEC and foF2 at a place, 7-day series at a place) and the TEC part of the weather publish: bad input '
                       '(400), unknown map (404), no weather file (503), gzip and 304', 'code',
     [('test_serverTEC.py', None)]),
    (SPINE, 'WEATHER', 'Weather endpoints answer on the live site: latest readings, a 24-hour series, CME events, '
                       'the aurora map, the aurora and absorption at a given latitude and longitude', 'site',
     ['endpoint:WEATHER now', 'endpoint:WEATHER solar wind speed', 'endpoint:WEATHER solar events',
      'endpoint:WEATHER aurora map', 'endpoint:WEATHER aurora at a place']),
    (SPINE, 'EO', 'No automated tests yet', 'none', []),
    (SPINE, 'ACKNOWLEDGMENTS', 'No automated tests yet', 'none', []),
    (SPINE, 'BUG REPORT (every section)', 'Visitor bug reports: stored without the IP address, field checks, size limits, '
                                          'honeypot, per-visitor rate limit, GET refused, server role recorded', 'code',
     [('test_server.py', ('test_bug_report_',))]),

    (BACKEND, 'Web server · files', 'Serves index.html and assets with the right content types; 404 for missing files; '
                                    'refuses code, databases, credentials and path tricks; query parameters', 'code',
     [('test_server.py', ('test_root_', 'test_js_asset', 'test_css_asset', 'test_svg_asset', 'test_missing_file',
                          'test_index_html', 'test_nested_asset', 'test_files_outside', 'test_get_param'))]),
    (BACKEND, 'Web server · site databases', 'Reads the site<Type>.db files, picks up a publish swap, falls back to the '
                                             'pre-refactor databases, releases connections on Windows', 'code',
     [('test_server.py', ('test_site_file', 'test_without_a_site_file', 'test_legacy_', 'test_windows_'))]),
    (BACKEND, 'Ingestion · Space-Track (NORAD)', 'Full and recent passes into ingestionSpaceTrack.db: what counts as a '
                                                 'change, objects dropping out, recorded GP records', 'code',
     [('test_ingestionSpaceTrack.py', None)]),
    (BACKEND, 'Ingestion · CelesTrak', 'Group memberships and radar sizes (RCS) into ingestionCelesTrak.db: interval, '
                                       '--force, RCS kept for good, canned responses', 'code',
     [('test_ingestionCelesTrak.py', None)]),
    (BACKEND, 'Ingestion · SatNOGS', 'Transmitters, plus the TLE feed used only as an ID crosswalk (designators), from '
                                     'recorded SatNOGS data', 'code',
     [('test_ingestionSatNOGS.py', None)]),
    (BACKEND, 'Ingestion · cosmic rays (Oulu)', 'Neutron-monitor CSV (Oulu, Dome C): hourly and monthly, provisional month, '
                                                'rejected headers and values, re-runs, failed runs, from recorded data', 'code',
     [('test_ingestionGCR.py', None)]),
    (BACKEND, 'Ingestion · SILSO sunspot number', 'Monthly sunspot file: parsing, definitive never replaced by provisional, '
                                                  'unchanged file not downloaded, rejected shapes', 'code',
     [('test_ingestionSILSO.py', None)]),
    (BACKEND, 'Ingestion · total electron content (CODE, GloTEC)', 'CODE IONEX files (rapid and 1, 2, 5-day predictions: grid, '
                                                                    '9999 = no value, issue time, the product the name promises) and NOAA GloTEC maps (72 x 72 cells, '
                                                                    'listing and computed-name fallback, never re-fetched, 7-day deletion), from recorded files', 'code',
     [('test_ingestionTEC.py', None)]),
    (BACKEND, 'Ingestion · NOAA SWPC maps', 'OVATION aurora grid and D-RAP absorption table: per-hemisphere maxima, '
                                            'oval edge, the full global maps, incomplete grids and shape surprises rejected, '
                                            'the daily deletion of 1-minute rows past 90 days', 'code',
     [('test_ingestionSWPC.py', ('test_ovation_', 'test_drap_', 'test_maps_job', 'test_a_newer_map',
                                 'test_prune_job'))]),
    (BACKEND, 'Ingestion · NOAA SWPC', 'Solar wind (active spacecraft only, gaps), GOES X-ray and protons (interleaved '
                                       'channels, misspelt key), Kp, F10.7, forecasts, events: validation, idempotent '
                                       're-runs, failed runs, from recorded data', 'code',
     [('test_ingestionSWPC.py', None)]),
    (BACKEND, 'Ingestion · GFZ Potsdam', 'Nowcast file and JSON API (Kp, ap, Ap, Hp30, Hp60, F10.7, sunspot number): '
                                         'missing values, definitive over preliminary, backfill, from recorded data', 'code',
     [('test_ingestionGFZ.py', None)]),
    (BACKEND, 'Ingestion · NASA DONKI', 'CME, HSS, GST, SEP, FLR and IPS events: rolling window, backfill, revised '
                                        'events, rejected shapes, from recorded data', 'code',
     [('test_ingestionDONKI.py', None)]),
    (BACKEND, 'Ingestion · space-weather samples', 'The shared samples and events tables: upserts, the 90-day live '
                                                   'window and deleting older 1-minute rows, the paced fetcher', 'code',
     [('test_spaceWeatherSamples.py', None)]),
    (BACKEND, 'Ingestion · GCAT','Parsing GCAT\'s TSV conventions (owners, programmes, mass, dates) and loading them', 'code',
     [('test_ingestGcat.py', None)]),
    (BACKEND, 'Ingestion · news feeds', 'RSS parsing (dates, entities, CDATA); filler and topic rules; pruning and '
                                        'tagging; database set-up', 'code',
     [('test_readNews.py', None), ('test_newsRules.py', None)]),
    (BACKEND, 'Publish · weather', 'siteWeather.db from the SWPC, GFZ and DONKI databases: native and hourly series, '
                                   'events, maps, derived F10.7A and storm scale, refusals, atomic swap', 'code',
     [('test_publishWeather.py', None)]),
    (BACKEND, 'Front end · chart code', 'assets/chartCore.js: the LAUNCHES charts and the pie drawn by the shared code are '
                                        'the same as the old per-panel code (node comparison); every assets/*.js passes '
                                        'node --check', 'code',
     [('test_chartCompare.py', None)]),
    (BACKEND, 'Publish · derived weather science', 'Spock\'s review: Newell function, G levels, storm list, S-events, DONKI SEP '
                                                   'grouping, CME filter, streams at L1, daily flare maximum', 'code',
     [('test_weatherDerived.py', None)]),
    (BACKEND, 'Documentation · database diagrams', 'dbDiagrams.py: schema reading, logical-join detection, Mermaid and SVG '
                                                   'output, a full run into a temporary folder', 'code',
     [('test_dbDiagrams.py', None)]),
    (BACKEND, 'Publish · site databases', 'publishSite.py: object selection, transmitter linking, sanity checks, '
                                          'atomic swap, publish records', 'code',
     [('test_publishSite.py', None)]),
    (BACKEND, 'Publish · satellite groups', 'Decision A: CelesTrak when available, the 3-month recent-launch rule, '
                                            'our own constellation rules', 'code',
     [('test_groupRules.py', None)]),
    (BACKEND, 'Scheduling · cron runner', 'Decision C (publish only after a change), the writers\' lock, run '
                                          'records for the freshness table', 'code',
     [('test_runIngestion.py', None), ('test_ingestionLog.py', None)]),
    (BACKEND, 'Scheduling · data freshness', 'Every source in the freshness table refreshed on schedule: none failing '
                                             'or overdue (is cron running?)', 'site',
     ['freshness']),
    (BACKEND, 'Shared modules', 'Database paths (incl. the legacy names), .env loader, HTTP fetch, Space-Track client', 'code',
     [('test_dbPaths.py', None), ('test_common.py', None)]),
    (BACKEND, 'Tools · bug log', '0_tools/bugs.py list / show / add / set, on a temporary copy of bugsDB.xlsx', 'code',
     [('test_bugsTool.py', None)]),

    (DEPLOYMENT, 'Migration & install', 'migrateLive.py (dry run, apply, rollback) and installReferenceDbs.py, in '
                                        'stand-in app folders', 'code',
     [('test_migrateLive.py', None)]),
    (DEPLOYMENT, 'Live checker', 'checkLiveDeployment.py\'s own judgements (freshness, privacy, reply shapes) on '
                                 'canned data', 'code',
     [('test_checkLiveDeployment.py', None)]),
    (DEPLOYMENT, 'Privacy · .htaccess', 'Private files are refused by the web server: databases, credentials, code, '
                                        'temporary files (first 1 KB requested only)', 'site',
     ['privacy']),
    (DEPLOYMENT, 'Deployed files', 'Frontend files on the site match this working copy (a difference = changes not '
                                   'yet deployed)', 'site',
     ['assets']),
]
UNASSIGNED = (BACKEND, 'Unassigned tests', 'Tests with no row in testHarness.py\'s UNITS yet: add them there', 'code')

TICK, UNTICK, PARTIAL, OFF = '☑', '☐', '◩', '–'
RESULT_TAGS = {'PASSED': 'pass', 'OK': 'pass', 'XFAIL': 'pass', 'FAILED': 'fail', 'ERROR': 'fail', 'FAIL': 'fail',
               'XPASS': 'warn', 'SKIPPED': 'warn', 'WARN': 'warn', 'NOTRUN': 'warn'}
SEVERITY = {'pass': 0, 'warn': 1, 'fail': 2}
PYTEST_LINE = re.compile(r'^(' + TEST_DIR + r'/\S+?::.+?) (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b')
SITE_LINE = re.compile(r'^\s+(OK|WARN|FAIL)\s+(.*)$')


# --- Finding the tests ------------------------------------------------------------------

def collectTests():
    """pytest's node ids for every test in 0_tests/, or raises RuntimeError."""
    result = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', TEST_DIR], cwd=REPO,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    ids = [line.strip() for line in result.stdout.splitlines() if '::' in line]
    if not ids:
        raise RuntimeError(f'pytest found no tests:\n{result.stdout}{result.stderr}')
    return ids


def docstrings(fileName):
    """{function name: first docstring line} for one test file."""
    try:
        tree = ast.parse(open(os.path.join(REPO, TEST_DIR, fileName), encoding='utf-8').read())
    except (OSError, SyntaxError):
        return {}
    return {node.name: ast.get_docstring(node).strip().splitlines()[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and ast.get_docstring(node)}


def testLabel(nodeId, docs):
    """'0_tests/f.py::test_some_thing[LEO]' -> 'Some thing [LEO]', or its docstring."""
    fileName, name = nodeId.split('::', 1)
    func, _, param = name.partition('[')
    text = docs.get(os.path.basename(fileName), {}).get(func)
    if not text:
        text = func[5:] if func.startswith('test_') else func
        text = text.replace('_', ' ')
        text = text[:1].upper() + text[1:]
    return f'{text} [{param}' if param else text


def assignTests(nodeIds):
    """[(unit, [node ids])] for UNITS (code units only), plus unassigned tests."""
    assigned = {i: [] for i, unit in enumerate(UNITS) if unit[3] == 'code'}
    leftover = []
    for nodeId in nodeIds:
        fileName, name = nodeId.split('::', 1)
        fileName = os.path.basename(fileName)
        for i in assigned:
            if any(f == fileName and (prefixes is None or name.startswith(prefixes)) for f, prefixes in UNITS[i][4]):
                assigned[i].append(nodeId)
                break
        else:
            leftover.append(nodeId)
    return assigned, leftover


def siteChecks(contents):
    """[(site-check id, label)] for a site unit's contents."""
    byName = {c[0]: c for c in cld.CHECKS}
    out = []
    for item in contents:
        if item.startswith('endpoint:'):
            name, path = byName[item[9:]][:2]
            out.append((item, f'{name}: /{path}'))
        elif item == 'privacy':
            out += [(f'privacy:{path}', f'{what}: /{path} refused') for path, what in cld.PRIVATE]
        elif item == 'assets':
            out += [(f'assets:{path}', path) for path in cld.ASSETS]
        else:
            out.append((item, 'Freshness table judged source by source'))
    return out


# --- Running the site checks (a separate process, so Stop can end it) -------------------

def runSiteChecks(base, low, high, ids):
    """Run the chosen checkLiveDeployment checks, pausing a random low-high
    seconds before each request (never under LIVE_MIN_DELAY away from a
    local server). Prints a heading per phase so the harness can tell
    freshness lines from the others."""
    if not base.startswith(('http://localhost', 'http://127.0.0.1')):
        low = max(low, LIVE_MIN_DELAY)
        high = max(high, low + 3)  # keep some random variation
    cld.DELAY_RANGE_SEC = (low, high)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    ids = set(ids)
    endpoints = [c for c in cld.CHECKS if f'endpoint:{c[0]}' in ids]
    if 'freshness' in ids and not any(c[1] == 'api/status' for c in endpoints):
        endpoints.insert(0, next(c for c in cld.CHECKS if c[1] == 'api/status'))
    private = [p for p in cld.PRIVATE if f'privacy:{p[0]}' in ids]
    assets = tuple(a for a in cld.ASSETS if f'assets:{a}' in ids)
    print(f'=== Site checks against {base}', flush=True)
    report = cld.Report()
    try:
        status = None
        if endpoints:
            print('[phase endpoint] Pages and APIs (does each answer correctly?):', flush=True)
            cld.CHECKS = endpoints
            status = cld.checkEndpoints(base, report, quick=False)
        if 'freshness' in ids:
            print('[phase freshness] Freshness (is every data source refreshed on schedule?):', flush=True)
            cld.checkFreshness(status, report)
        if private:
            print('[phase privacy] Privacy (are private files refused by the web server?):', flush=True)
            cld.PRIVATE = private
            cld.checkPrivacy(base, report)
        if assets:
            print('[phase assets] Assets (do the deployed files match this working copy?):', flush=True)
            cld.ASSETS = assets
            cld.checkAssets(base, report)
    except (cld.urllib.error.URLError, cld.socket.timeout, ConnectionError) as error:
        print(f'  FAIL  Site unreachable at {base}: {error}', flush=True)
        return 2
    c = report.counts
    print(f"=== Site checks: {c['OK']} OK, {c['WARN']} warnings, {c['FAIL']} failures", flush=True)
    return 1 if c['FAIL'] else 0


def siteLineId(phase, text, ids):
    """Which ticked site check a line of output is about, or None."""
    if phase == 'freshness':
        return 'freshness'
    for checkId in ids:
        kind, _, key = checkId.partition(':')
        if kind != phase:
            continue
        if kind == 'endpoint' and text.startswith(key + ' '):
            return checkId
        if kind == 'privacy' and f'/{key} ' in text + ' ':
            return checkId
        if kind == 'assets' and text.startswith(key + ' '):
            return checkId
    return None


# --- The window --------------------------------------------------------------------------

class Harness:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, scrolledtext
        self.tk, self.root = tk, root
        self.environment = tk.StringVar(value='DEV')
        self.pace = tk.StringVar(value=DEFAULT_PACE['DEV'])
        self.unlocked = tk.BooleanVar(value=False)
        self.ticked, self.results = set(), {}
        self.leafOf = {}       # tree row -> test id ('code:<node id>' / 'site:<check id>'), leaves only
        self.kindOf = {}       # tree row -> 'code' / 'site' / 'none' / 'heading'
        self.process, self.stopping, self.output = None, False, queue.Queue()
        self.loadSettings()

        root.title('LCARS-FAS test harness')
        root.geometry('1400x880')

        self.banner = tk.Frame(root, padx=10, pady=8)
        self.banner.pack(fill='x')
        self.bannerTitle = tk.Label(self.banner, text='TEST ENVIRONMENT', font=('TkDefaultFont', 11, 'bold'), fg='white')
        self.bannerTitle.pack(side='left', padx=(0, 12))
        self.envButtons = {}
        for key, env in ENVIRONMENTS.items():
            button = tk.Radiobutton(self.banner, text=env['label'], variable=self.environment, value=key,
                                    indicatoron=0, width=18, font=('TkDefaultFont', 12, 'bold'), relief='raised',
                                    bd=3, command=self.environmentChanged)
            button.pack(side='left', padx=4)
            self.envButtons[key] = button
        self.bannerNote = tk.Label(self.banner, fg='white', justify='left', anchor='w', wraplength=760)
        self.bannerNote.pack(side='left', padx=14, fill='x', expand=True)

        bar = tk.Frame(root, padx=8, pady=6)
        bar.pack(fill='x')
        for text, command in (('Tick all', self.tickAll), ('Tick none', self.tickNone), ('Tick failed', self.tickFailed),
                              ('Expand all', lambda: self.expand(True)), ('Collapse all', lambda: self.expand(False))):
            ttk.Button(bar, text=text, command=command).pack(side='left', padx=2)
        tk.Label(bar, text='  Pace:').pack(side='left')
        self.paceBox = ttk.Combobox(bar, textvariable=self.pace, state='readonly', width=20)
        self.paceBox.pack(side='left')
        self.paceBox.bind('<<ComboboxSelected>>', lambda e: self.paceChanged())
        self.lockBox = tk.Checkbutton(bar, variable=self.unlocked, command=self.refresh, fg='#b00020',
                                      text='Allow probes of private files (.env, .htaccess, server.py...)')
        self.lockBox.pack(side='left', padx=14)
        self.stopButton = ttk.Button(bar, text='Stop', command=self.stop, state='disabled')
        self.stopButton.pack(side='right', padx=2)
        self.runButton = ttk.Button(bar, text='▶ Run ticked', command=self.run)
        self.runButton.pack(side='right', padx=2)
        self.status = tk.Label(bar, anchor='w')
        self.status.pack(side='left', padx=12, fill='x', expand=True)

        panes = ttk.PanedWindow(root, orient='vertical')
        panes.pack(fill='both', expand=True, padx=8, pady=(0, 8))
        tableFrame = ttk.Frame(panes)
        self.tree = ttk.Treeview(tableFrame, columns=('what', 'run'), selectmode='browse')
        self.tree.heading('#0', text='Functionality', anchor='w')
        self.tree.heading('what', text='What is tested', anchor='w')
        self.tree.heading('run', text='Run')
        self.tree.column('#0', width=300, stretch=False)
        self.tree.column('what', width=960, stretch=True)
        self.tree.column('run', width=60, anchor='center', stretch=False)
        scroll = ttk.Scrollbar(tableFrame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.tag_configure('heading', font=('TkDefaultFont', 10, 'bold'), background='#e3e7f0')
        self.tree.tag_configure('off', foreground='#9a9a9a')
        self.tree.tag_configure('pass', background='#d6f2d6')
        self.tree.tag_configure('warn', background='#fbeac0')
        self.tree.tag_configure('fail', background='#f6cccc')
        self.tree.bind('<Button-1>', self.clicked)
        self.tree.bind('<space>', lambda e: self.toggle(self.tree.focus()))
        panes.add(tableFrame, weight=3)

        self.log = scrolledtext.ScrolledText(panes, height=12, font=('Courier', 9), wrap='none')
        self.log.tag_configure('fail', foreground='#b00020')
        self.log.tag_configure('warn', foreground='#a15c00')
        self.log.tag_configure('pass', foreground='#1b5e20')
        panes.add(self.log, weight=1)

        root.protocol('WM_DELETE_WINDOW', self.close)
        self.build()
        self.environmentChanged()
        root.after(100, self.drain)

    # --- Settings ---

    def loadSettings(self):
        try:
            saved = json.load(open(SETTINGS, encoding='utf-8'))
            self.environment.set(saved.get('environment', 'DEV'))
            self.ticked = set(saved.get('ticked', []))
        except (OSError, ValueError):
            pass

    def saveSettings(self):
        try:
            with open(SETTINGS, 'w', encoding='utf-8') as f:
                json.dump({'environment': self.environment.get(), 'ticked': sorted(self.ticked)}, f)
        except OSError:
            pass

    # --- The table ---

    def build(self):
        self.status.config(text='Finding tests...')
        self.root.update_idletasks()
        try:
            nodeIds = collectTests()
        except RuntimeError as error:
            nodeIds = []
            self.write(str(error) + '\n', 'fail')
        self.nodeIds = set(nodeIds)
        docs = {f: docstrings(f) for f in {os.path.basename(n.split('::')[0]) for n in nodeIds}}
        assigned, leftover = assignTests(nodeIds)
        units = [(unit, assigned.get(i)) for i, unit in enumerate(UNITS)]
        if leftover:
            units.append((UNASSIGNED + ([],), leftover))
        headings = {}
        for unit, tests in units:
            heading, functionality, what, kind, contents = unit
            if heading not in headings:
                headings[heading] = self.tree.insert('', 'end', text=heading, open=True, tags=('heading',))
                self.kindOf[headings[heading]] = 'heading'
            if kind == 'code':
                children = [('code:' + n, testLabel(n, docs)) for n in tests]
                what = f'Code test · {what}  ({len(children)} tests)'
            elif kind == 'site':
                children = [('site:' + i, label) for i, label in siteChecks(contents)]
                what = f'Site check · {what}' + (f'  ({len(children)} checks)' if len(children) > 1 else '')
            else:
                children = []
            row = self.tree.insert(headings[heading], 'end', text=functionality, values=(what, ''))
            self.kindOf[row] = kind
            if len(children) == 1 and kind == 'site':
                self.leafOf[row] = children[0][0]
                continue
            for testId, label in children:
                child = self.tree.insert(row, 'end', text='', values=(label, ''))
                self.kindOf[child] = kind
                self.leafOf[child] = testId
        self.ticked &= set(self.leafOf.values())
        self.status.config(text=f'{len(nodeIds)} code tests and {sum(1 for t in self.leafOf.values() if t.startswith("site:"))} '
                                'site checks found.')

    def enabled(self, row):
        kind = self.kindOf[row]
        if kind == 'site':
            return self.unlocked.get() or not self.leafOf.get(row, '').startswith('site:' + PROBE_PREFIX)
        return kind == 'code' and self.environment.get() == 'DEV'

    def leaves(self, row):
        """The tickable rows at or under a row, in this environment."""
        if row in self.leafOf:
            return [row] if self.enabled(row) else []
        return [leaf for child in self.tree.get_children(row) for leaf in self.leaves(child)]

    def refresh(self, row=''):
        """Redraw tickboxes and result colours, bottom up."""
        for child in self.tree.get_children(row):
            self.refresh(child)
        if not row:
            return
        leaves = self.leaves(row)
        if not leaves:
            box = OFF
        else:
            count = sum(1 for leaf in leaves if self.leafOf[leaf] in self.ticked)
            box = TICK if count == len(leaves) else UNTICK if count == 0 else PARTIAL
        self.tree.set(row, 'run', box)
        tags = [t for t in self.tree.item(row, 'tags') if t == 'heading']
        if not leaves and self.kindOf[row] != 'heading':
            tags.append('off')
        outcomes = [self.results[self.leafOf[leaf]] for leaf in leaves if self.leafOf[leaf] in self.results]
        if outcomes and self.kindOf[row] != 'heading':
            tags.append(max(outcomes, key=SEVERITY.get))
        self.tree.item(row, tags=tags)

    def clicked(self, event):
        if self.tree.identify_region(event.x, event.y) == 'cell' and self.tree.identify_column(event.x) == '#2':
            self.toggle(self.tree.identify_row(event.y))

    def toggle(self, row):
        leaves = self.leaves(row) if row else []
        if not leaves:
            return
        ids = {self.leafOf[leaf] for leaf in leaves}
        if ids <= self.ticked:
            self.ticked -= ids
        else:
            self.ticked |= ids
        self.refresh()

    def tickAll(self):
        self.ticked |= {self.leafOf[leaf] for leaf in self.leaves('')}
        self.refresh()

    def tickNone(self):
        self.ticked -= {self.leafOf[leaf] for leaf in self.leaves('')}
        self.refresh()

    def tickFailed(self):
        visible = {self.leafOf[leaf] for leaf in self.leaves('')}
        self.ticked = (self.ticked - visible) | {t for t in visible if self.results.get(t) == 'fail'}
        self.refresh()

    def expand(self, opened):
        def walk(row):
            for child in self.tree.get_children(row):
                if self.kindOf[child] != 'heading':
                    self.tree.item(child, open=opened)
                walk(child)
        walk('')

    def environmentChanged(self):
        key = self.environment.get()
        env = ENVIRONMENTS[key]
        for other, button in self.envButtons.items():
            selected = other == key
            button.config(bg=env['colour'] if selected else '#e0e0e0', fg='white' if selected else '#555555',
                          selectcolor=env['colour'], relief='sunken' if selected else 'raised',
                          activebackground=ENVIRONMENTS[other]['colour'], activeforeground='white')
        self.banner.config(bg=env['colour'])
        self.bannerTitle.config(bg=env['colour'])
        self.bannerNote.config(bg=env['colour'], text=f"Target: {env['base']}\n{env['note']}")
        self.root.title(f"LCARS-FAS test harness: {env['label']}")
        self.paceBox.config(values=PACES_BY_ENV[key])
        self.pace.set(DEFAULT_PACE[key])
        self.unlocked.set(False)
        self.results.clear()
        self.refresh()

    def paceChanged(self):
        self.status.config(text=f'Pace: {self.pace.get()}.')

    # --- Running ---

    def write(self, text, tag=None):
        self.log.insert('end', text, tag)
        self.log.see('end')

    def run(self):
        from tkinter import messagebox
        ticked = {self.leafOf[leaf] for leaf in self.leaves('')} & self.ticked
        code = sorted(t[5:] for t in ticked if t.startswith('code:'))
        site = sorted(t[5:] for t in ticked if t.startswith('site:'))
        if not code and not site:
            self.status.config(text='Nothing ticked.')
            return
        env = ENVIRONMENTS[self.environment.get()]
        low, high = PACES[self.pace.get()]
        probes = sum(1 for s in site if s.startswith(PROBE_PREFIX))
        if self.environment.get() == 'LIVE':
            minutes = len(site) * (max(low, LIVE_MIN_DELAY) + high) / 2 / 60
            probeNote = (f'\n\nIncluding {probes} probes of private files (.env, server.py, databases...): '
                         'scanners request these same paths.' if probes else '')
            if not messagebox.askokcancel('Run against LIVE',
                                          f"{len(site)} site checks against {env['base']}: read-only GET requests, "
                                          f'{self.pace.get()}, about {max(1, round(minutes))} min.{probeNote}'
                                          '\n\nGo ahead?'):
                return
        self.saveSettings()
        self.results = {t: r for t, r in self.results.items() if t not in ticked}
        self.refresh()
        self.log.delete('1.0', 'end')
        self.runButton.config(state='disabled')
        self.stopButton.config(state='normal')
        self.stopping = False
        self.status.config(text=f"Running {len(code)} code tests and {len(site)} site checks ({env['label']})...")
        threading.Thread(target=self.worker, args=(code, site, env['base'], PACES[self.pace.get()]),
                         daemon=True).start()

    def worker(self, code, site, base, pace):
        """Runs in the background; sends ('line', text) and ('result', id, level) to the window."""
        environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'}
        if code:
            whole = self.wholeFiles(code)
            argsFile = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8')
            argsFile.write('\n'.join(whole))
            argsFile.close()
            self.stream([sys.executable, '-m', 'pytest', '-v', '--color=no', '-p', 'no:cacheprovider',
                         '@' + argsFile.name], environment, self.pytestLine, code)
            os.unlink(argsFile.name)
        if site and not self.stopping:
            phase = {'value': None, 'worst': {}}
            self.stream([sys.executable, os.path.abspath(__file__), '--site-checks', base, str(pace[0]), str(pace[1])] + site, environment,
                        lambda line: self.siteLine(line, phase, site), ['site:' + s for s in site])
        self.output.put(('done',))

    def wholeFiles(self, code):
        """Node ids, with a file named once when all its tests are ticked (shorter command)."""
        byFile = {}
        for nodeId in code:
            byFile.setdefault(nodeId.split('::')[0], []).append(nodeId)
        out = []
        for fileName, ids in byFile.items():
            every = [n for n in self.nodeIds if n.startswith(fileName + '::')]
            out += [fileName] if len(ids) == len(every) else ids
        return out

    def stream(self, command, environment, parse, expected):
        expected = ['code:' + e if not e.startswith('site:') else e for e in expected]
        self.output.put(('line', '$ ' + ' '.join(os.path.basename(c) if c == sys.executable else c
                                                 for c in command[:8]) + (' ...' if len(command) > 8 else '') + '\n'))
        self.process = subprocess.Popen(command, cwd=REPO, env=environment, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        seen = set()
        for line in self.process.stdout:
            result = parse(line.rstrip('\n'))
            if result:
                seen.add(result[0])
                self.output.put(('result',) + result)
            self.output.put(('line', line, RESULT_TAGS.get(result[1]) if result else None))
        self.process.wait()
        for testId in expected:
            if testId not in seen:
                self.output.put(('result', testId, 'NOTRUN'))
        self.process = None

    def pytestLine(self, line):
        match = PYTEST_LINE.match(line)
        return ('code:' + match.group(1), match.group(2)) if match else None

    def siteLine(self, line, phase, site):
        if line.startswith('[phase '):
            phase['value'] = line[7:line.index(']')]
            return None
        match = SITE_LINE.match(line)
        if not match:
            return None
        checkId = siteLineId(phase['value'], match.group(2), site)
        if checkId is None:
            return None
        level = RESULT_TAGS[match.group(1)]
        worst = phase['worst'].get(checkId)
        if worst and SEVERITY[RESULT_TAGS[worst]] > SEVERITY[level]:  # freshness: keep the worst source's verdict
            return None
        phase['worst'][checkId] = match.group(1)
        return ('site:' + checkId, match.group(1))

    def drain(self):
        """Moves output from the background run into the window."""
        changed = False
        try:
            while True:
                item = self.output.get_nowait()
                if item[0] == 'line':
                    self.write(item[1] if item[1].endswith('\n') else item[1] + '\n', item[2] if len(item) > 2 else None)
                elif item[0] == 'result':
                    self.results[item[1]] = RESULT_TAGS[item[2]]
                    changed = True
                else:
                    self.finished()
        except queue.Empty:
            pass
        if changed:
            self.refresh()
        self.root.after(100, self.drain)

    def finished(self):
        self.runButton.config(state='normal')
        self.stopButton.config(state='disabled')
        self.unlocked.set(False)
        self.refresh()
        counts = {level: sum(1 for r in self.results.values() if r == level) for level in SEVERITY}
        verdict = 'STOPPED' if self.stopping else 'FAILED' if counts['fail'] else 'PASSED'
        self.status.config(text=f"{verdict}: {counts['pass']} passed, {counts['warn']} warnings / skipped / not run, "
                                f"{counts['fail']} failed.")

    def stop(self):
        self.stopping = True
        if self.process:
            self.process.kill()

    def close(self):
        self.stop()
        self.saveSettings()
        self.root.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['--site-checks']:
        return runSiteChecks(argv[1], float(argv[2]), float(argv[3]), argv[4:])
    import tkinter as tk
    root = tk.Tk()
    Harness(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
