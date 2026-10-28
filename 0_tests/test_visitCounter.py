"""Tests for scripts/visitCounter.py (counting visits by city, keeping no address)
and 0_tools/buildGeoIPDb.py, in a temporary database folder, with a tiny lookup
built from sample rows. The addresses are real public ones only because the
code skips private and documentation ranges; nothing touches the network."""

import io
import os
import sqlite3
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'scripts'))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), '0_tools'))
import buildGeoIPDb  # noqa: E402
import dbPaths  # noqa: E402
import server  # noqa: E402
import visitCounter as vc  # noqa: E402

SAMPLE = '''ip_start,ip_end,continent,country,stateprov,city,latitude,longitude
8.8.8.0,8.8.8.127,NA,US,California,Mountain View,37.386,-122.0838
8.8.8.128,8.8.8.255,NA,US,California,Mountain View,37.386,-122.0838
8.8.9.0,8.8.9.255,NA,US,California,,37.0,-120.0
8.8.10.0,8.8.10.255,NA,US,California,Nowhere,,
1.1.1.0,1.1.1.255,OC,AU,New South Wales,Sydney,-33.8688,151.2093
2001:4860:4860::,2001:4860:4860::ffff,NA,US,California,Mountain View,37.386,-122.0838
'''
BROWSER = 'Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0'


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(dbPaths, 'LEGACY', False)
    vc._recent.clear()
    return tmp_path


@pytest.fixture
def geoip(folder):
    csvPath = folder / 'sample.csv'
    csvPath.write_text(SAMPLE, encoding='utf-8')
    buildGeoIPDb.buildGeoIP(str(csvPath), dbPaths.dbPath(dbPaths.GEOIP_DB))
    return folder


def environ(address, agent=BROWSER, forwarded=None):
    env = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/api/visit', 'QUERY_STRING': '', 'REMOTE_ADDR': address,
           'HTTP_USER_AGENT': agent, 'wsgi.input': io.BytesIO(b''), 'wsgi.errors': sys.stderr}
    if forwarded:
        env['HTTP_X_FORWARDED_FOR'] = forwarded
    return env


def usageRows(folder):
    conn = sqlite3.connect(str(folder / dbPaths.USAGE_DB))
    try:
        return conn.execute('SELECT city, country, logins FROM logins ORDER BY city').fetchall()
    finally:
        conn.close()


# --- the lookup builder -------------------------------------------------------

def test_builder_merges_adjacent_ranges_and_skips_unusable_rows(geoip):
    conn = sqlite3.connect(dbPaths.dbPath(dbPaths.GEOIP_DB))
    assert conn.execute('SELECT COUNT(*) FROM ipRanges4').fetchone()[0] == 3   # two adjacent Mountain View halves merged; Nowhere skipped
    assert conn.execute('SELECT COUNT(*) FROM ipRanges6').fetchone()[0] == 1
    cities = {row[0] for row in conn.execute('SELECT city FROM places')}
    assert cities == {'Mountain View', 'Unknown city', 'Sydney'}
    assert isinstance(conn.execute('SELECT startIP FROM ipRanges6').fetchone()[0], bytes)
    conn.close()


# --- who is counted ---------------------------------------------------------------

def test_bots_and_missing_browsers_are_not_visitors():
    assert vc.isBot('Googlebot/2.1') and vc.isBot('curl/8.4') and vc.isBot('') and vc.isBot(None)
    assert vc.isBot('LCARS-FAS checkLiveDeployment/1.1')
    assert not vc.isBot(BROWSER)


def test_the_address_is_the_remote_one_or_the_first_public_forwarded_one():
    import ipaddress
    assert vc.clientAddress({'REMOTE_ADDR': '8.8.8.8'}) == ipaddress.ip_address('8.8.8.8')
    assert vc.clientAddress({'REMOTE_ADDR': '10.0.0.5', 'HTTP_X_FORWARDED_FOR': '192.168.1.1, 1.1.1.1, 8.8.8.8'}) \
        == ipaddress.ip_address('1.1.1.1')
    assert vc.clientAddress({'REMOTE_ADDR': '8.8.8.8', 'HTTP_X_FORWARDED_FOR': '1.1.1.1'}) == ipaddress.ip_address('8.8.8.8')
    assert vc.clientAddress({'REMOTE_ADDR': '127.0.0.1'}) is None
    assert vc.clientAddress({'REMOTE_ADDR': '203.0.113.7'}) is None   # a documentation address
    assert vc.clientAddress({'REMOTE_ADDR': '::ffff:8.8.8.8'}) == ipaddress.ip_address('8.8.8.8')
    assert vc.clientAddress({'REMOTE_ADDR': 'garbage'}) is None


def test_lookup_finds_ipv4_and_ipv6_places_and_marks_the_rest_unknown(geoip):
    import ipaddress
    assert vc.lookupPlace(ipaddress.ip_address('8.8.8.200'))[:2] == ('Mountain View', 'US')
    assert vc.lookupPlace(ipaddress.ip_address('1.1.1.1'))[:2] == ('Sydney', 'AU')
    assert vc.lookupPlace(ipaddress.ip_address('2001:4860:4860::8888'))[:2] == ('Mountain View', 'US')
    assert vc.lookupPlace(ipaddress.ip_address('9.9.9.9')) == vc.UNKNOWN_PLACE


def test_no_lookup_database_means_no_counting(folder):
    assert vc.countVisit(environ('8.8.8.8')) is False
    assert not (folder / dbPaths.USAGE_DB).exists()


# --- counting -------------------------------------------------------------------------

def test_a_visit_is_counted_by_city_and_a_repeat_within_the_window_is_not(geoip):
    assert vc.countVisit(environ('8.8.8.8'), now=1000.0) is True
    assert vc.countVisit(environ('8.8.8.8'), now=1000.0 + vc.DEDUPE_SEC - 1) is False
    assert vc.countVisit(environ('8.8.8.9'), now=1000.0) is True            # another visitor, same city
    assert vc.countVisit(environ('1.1.1.1'), now=1000.0) is True
    assert vc.countVisit(environ('8.8.8.8'), now=1000.0 + vc.DEDUPE_SEC + 1) is True   # back after the window
    assert usageRows(geoip) == [('Mountain View', 'US', 3), ('Sydney', 'AU', 1)]


def test_bots_private_addresses_and_unknown_places(geoip):
    assert vc.countVisit(environ('8.8.8.8', agent='Googlebot/2.1')) is False
    assert vc.countVisit(environ('192.168.0.9')) is False
    assert vc.countVisit(environ('9.9.9.9')) is True                       # public, not in the data
    assert usageRows(geoip) == [('Unknown', '??', 1)]


def test_no_address_is_written_anywhere(geoip, capsys):
    for address in ('8.8.8.8', '1.1.1.1', '2001:4860:4860::8888'):
        vc.countVisit(environ(address, forwarded='8.8.8.250'))
    raw = (geoip / dbPaths.USAGE_DB).read_bytes()
    for text in (b'8.8.8.8', b'1.1.1.1', b'8.8.8.250', b'2001:4860'):
        assert text not in raw
    # nor in the digests kept in memory, nor in anything printed
    assert all(len(key) == 32 for key in vc._recent)
    out = capsys.readouterr()
    assert '8.8.8' not in out.out + out.err


def test_a_failure_is_swallowed_without_the_address(geoip, capsys, monkeypatch):
    def boom(place, day=None, path=None):
        raise RuntimeError('database 8.8.8.8 exploded')
    monkeypatch.setattr(vc, 'recordVisit', boom)
    assert vc.countVisit(environ('8.8.8.8')) is False
    assert '8.8.8.8' not in capsys.readouterr().err   # only the error's type name is printed


def test_the_visit_endpoint_answers_204_and_counts(geoip):
    captured = {}
    body = server.application(environ('1.1.1.1'), lambda status, headers: captured.update(status=status))
    assert captured['status'] == '204 No Content' and b''.join(body) == b''
    assert usageRows(geoip) == [('Sydney', 'AU', 1)]
