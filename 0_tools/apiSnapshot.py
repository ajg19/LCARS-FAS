"""Snapshot every GET API endpoint's JSON, and compare two snapshots.

Calls server.py's WSGI application in-process (no running server
needed), against whatever databases the working copy has. Written for
the database refactor (0_documentation/plans/dbRefactorPlan.md): step 2 takes
the baseline, step 13 compares the refactored site against it.

    python 0_tools/apiSnapshot.py take LABEL      -> 0_testReports/apiSnapshots/LABEL/
    python 0_tools/apiSnapshot.py compare OLD NEW

Snapshots are large (the full active-satellite list is in there) and are
gitignored. Endpoints whose output depends on the clock (VOLATILE) are
still compared, but their differences are flagged as expected.
"""

import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(ROOT, '0_testReports', 'apiSnapshots')

STATUS = ('active', 'all')
KINDS = ('satellites', 'spacecraft', 'objects')
SPACEX = ('with', 'without')
ON_ORBIT_CHARTS = (
    'active-by-regime', 'age', 'altitude', 'altitude-vs-inclination', 'band', 'band-by-mission',
    'band-by-regime', 'buses', 'catalogue-by-type', 'country-owner', 'debris-altitude',
    'debris-history', 'debris-inclination', 'debris-origin', 'geo-belt', 'inclination-by-regime',
    'manufacturers', 'mission', 'payloads-by-year', 'rocket-bodies-country',
    'rocket-bodies-vehicle', 'sector-by-country',
)
# ISS, Hubble, a Starlink, a GEO comsat, a rocket body.
SAMPLE_NORAD_IDS = (25544, 20580, 44713, 41866, 27386)

# Output depends on the time of the request -- or, for the GEO belt, on
# when the stats were built (longitudes are propagated to that moment).
VOLATILE = ('api_status', 'api_sky_satellites', 'api_on-orbit_chart_geo-belt')


def requests():
    """(name, path, query) for every GET endpoint and the filter
    combinations the pages use."""
    out = [
        ('api_status', '/api/status', ''),
        ('api_news', '/api/news', ''),
        ('api_news_topic-counts', '/api/news/topic-counts', ''),
        ('api_ground-segment-assets', '/api/ground-segment-assets', ''),
        ('api_sky_catalogue', '/api/sky/catalogue', ''),
        ('api_sky_satellites', '/api/sky/satellites', ''),
        ('api_orbital-objects_active', '/api/orbital-objects/active', ''),
        ('api_orbital-objects_active-nonpayload', '/api/orbital-objects/active-nonpayload', ''),
        ('api_orbital-objects_filter-options', '/api/orbital-objects/filter-options', ''),
        ('api_orbital-objects_ids', '/api/orbital-objects', 'ids=' + ','.join(map(str, SAMPLE_NORAD_IDS))),
        ('api_orbital-objects_search_all', '/api/orbital-objects/search', 'limit=500'),
        ('api_orbital-objects_search_starlink', '/api/orbital-objects/search', 'group=starlink&limit=500'),
        ('api_orbital-objects_search_stations', '/api/orbital-objects/search', 'group=stations'),
        ('api_orbital-objects_search_name', '/api/orbital-objects/search', 'name=ISS'),
    ]
    for norad_id in SAMPLE_NORAD_IDS:
        out.append((f'api_sky_object_{norad_id}', '/api/sky/object', f'noradID={norad_id}'))
    for status in STATUS:
        for kind in KINDS:
            for spacex in SPACEX:
                q = f'status={status}&kind={kind}&spacex={spacex}'
                tag = f'{status}_{kind}_{spacex}'
                for ep in ('nationality', 'regimes', 'inclination', 'sector', 'owners'):
                    out.append((f'api_on-orbit_{ep}_{tag}', f'/api/on-orbit/{ep}', q))
                for chart in ON_ORBIT_CHARTS:
                    out.append((f'api_on-orbit_chart_{chart}_{tag}', '/api/on-orbit/chart', f'name={chart}&{q}'))
    for spacex in SPACEX:
        for outcome in ('all', 'success'):
            q = f'spacex={spacex}&outcome={outcome}'
            for ep in ('per-year', 'payloads-launched', 'by-country', 'reentries'):
                out.append((f'api_launches_{ep}_{spacex}_{outcome}', f'/api/launches/{ep}', q))
    return out


def call(application, path, query):
    result = {}

    def start_response(status, headers, exc_info=None):
        result['status'] = status
        result['headers'] = dict(headers)

    body = b''.join(application({
        'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'QUERY_STRING': query,
        'SERVER_NAME': 'localhost', 'SERVER_PORT': '80', 'wsgi.url_scheme': 'http',
    }, start_response))
    if result.get('headers', {}).get('Content-Encoding') == 'gzip':
        import gzip
        body = gzip.decompress(body)
    return result['status'], body


def take(label):
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import server
    out_dir = os.path.join(SNAPSHOT_DIR, label)
    os.makedirs(out_dir, exist_ok=True)
    index = {}
    for name, path, query in requests():
        status, body = call(server.application, path, query)
        try:
            data = json.loads(body)
        except ValueError:
            data = {'_nonJson': body[:200].decode('utf-8', 'replace')}
        with open(os.path.join(out_dir, name + '.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, sort_keys=True, ensure_ascii=False)
        index[name] = {'path': path, 'query': query, 'status': status, 'bytes': len(body),
                       'sha1': hashlib.sha1(body).hexdigest()}
        if not status.startswith('200'):
            print(f'  {status:24s} {name}')
    with open(os.path.join(out_dir, '_index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=1, sort_keys=True)
    print(f'{len(index)} endpoints -> {out_dir}')


def compare(old_label, new_label):
    def load(label):
        with open(os.path.join(SNAPSHOT_DIR, label, '_index.json'), encoding='utf-8') as f:
            return json.load(f)

    old, new = load(old_label), load(new_label)
    same = 0
    for name in sorted(set(old) | set(new)):
        if name not in new or name not in old:
            print(f'  {"MISSING in " + (new_label if name not in new else old_label):30s} {name}')
            continue
        o, n = old[name], new[name]
        if o['status'] != n['status']:
            print(f'  STATUS {o["status"]} -> {n["status"]:14s} {name}')
        elif o['sha1'] != n['sha1']:
            note = ' (time-dependent, expected)' if name.startswith(VOLATILE) else ''
            print(f'  CHANGED {o["bytes"]:>9,} -> {n["bytes"]:>9,} bytes  {name}{note}')
        else:
            same += 1
    print(f'{same} of {len(old)} endpoints identical')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('take').add_argument('label')
    p = sub.add_parser('compare')
    p.add_argument('old')
    p.add_argument('new')
    args = parser.parse_args()
    if args.cmd == 'take':
        take(args.label)
    else:
        compare(args.old, args.new)
