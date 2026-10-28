"""Counts visits to the site by city, and keeps no address.

The page sends one small POST to /api/visit per browser session (assets/lcars.js);
server.py hands it to countVisit(). For each visit this module

  1. ignores bots (by their browser string);
  2. takes the visitor's public address from the request, in memory only;
  3. looks it up in databases/ingestionGeoIP.db (built on the laptop from a
     DB-IP City Lite file by 0_tools/buildGeoIPDb.py) to get a city, country
     and position;
  4. skips a repeat from the same address within DEDUPE_SEC, remembering only
     a salted hash of the address, in memory, never written anywhere and lost
     when the process restarts;
  5. adds one to that day's count for the city in databases/inboxUsage.db,
     table logins(day, city, country, latitude, longitude, logins).

The address itself is never written to a database or a log, and no exception
message that could contain it is printed. With no lookup database deployed a
visit is not counted at all (rather than being counted as "Unknown" for ever);
an address that is public but not in the data is counted as Unknown. Private,
loopback and documentation addresses (a developer's own machine) are not
counted. The host's own web-server access logs still hold addresses; that is
outside this code.

"Logins" here are visits (a browser session starting); if the site later gets
real accounts, the same table can count those instead.
"""

import hashlib
import ipaddress
import os
import pathlib
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone

import dbPaths

DEDUPE_SEC = 30 * 60
MAX_REMEMBERED = 20000
BOT_WORDS = ('bot', 'crawl', 'spider', 'slurp', 'curl', 'wget', 'python-requests', 'headless', 'monitor',
             'check', 'preview', 'lighthouse', 'facebookexternalhit')
UNKNOWN_PLACE = ('Unknown', '??', None, None)   # city, country, latitude, longitude

_salt = os.urandom(16)
_recent = {}
_lock = threading.Lock()


def isBot(userAgent):
    agent = (userAgent or '').lower()
    return not agent or any(word in agent for word in BOT_WORDS)


def clientAddress(environ):
    """The visitor's public address as an ipaddress object, or None. REMOTE_ADDR
    is used if it is public; if it is private or loopback (a proxy in front),
    the first public address in X-Forwarded-For."""
    candidates = [environ.get('REMOTE_ADDR', '')] + [part.strip() for part in environ.get('HTTP_X_FORWARDED_FOR', '').split(',')]
    for text in candidates:
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            continue
        if getattr(address, 'ipv4_mapped', None):
            address = address.ipv4_mapped
        if address.is_global:
            return address
    return None


def lookupPlace(address, path=None):
    """(city, country, latitude, longitude) for a public address, UNKNOWN_PLACE
    if the data has no entry for it, or None if there is no lookup database."""
    path = path or dbPaths.dbPath(dbPaths.GEOIP_DB)
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(pathlib.Path(path).as_uri() + '?mode=ro', uri=True)
    try:
        if address.version == 4:
            table, key = 'ipRanges4', int(address)
        else:
            table, key = 'ipRanges6', address.packed
        # Ranges do not overlap: the one that could hold the address is the last to start at or before it.
        row = conn.execute(f'SELECT endIP, placeID FROM {table} WHERE startIP <= ? ORDER BY startIP DESC LIMIT 1',
                           (key,)).fetchone()
        if row is None or key > row[0]:
            return UNKNOWN_PLACE
        place = conn.execute('SELECT city, country, latitude, longitude FROM places WHERE placeID = ?', (row[1],)).fetchone()
        return tuple(place) if place else UNKNOWN_PLACE
    finally:
        conn.close()


def seenRecently(address, now=None):
    """True if this address was counted within DEDUPE_SEC; otherwise remembers
    it (a salted hash, in memory only) and returns False."""
    now = time.time() if now is None else now
    digest = hashlib.sha256(_salt + address.packed).digest()
    with _lock:
        last = _recent.get(digest)
        if last is not None and now - last < DEDUPE_SEC:
            return True
        if len(_recent) >= MAX_REMEMBERED:
            for key in [key for key, when in _recent.items() if now - when >= DEDUPE_SEC]:
                del _recent[key]
            if len(_recent) >= MAX_REMEMBERED:
                _recent.clear()
        _recent[digest] = now
    return False


def recordVisit(place, day=None, path=None):
    city, country, latitude, longitude = place
    day = day or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    conn = sqlite3.connect(path or dbPaths.dbPath(dbPaths.USAGE_DB), timeout=5)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS logins (day TEXT NOT NULL, city TEXT NOT NULL, country TEXT NOT NULL, '
                     'latitude REAL, longitude REAL, logins INTEGER NOT NULL, PRIMARY KEY (day, city, country))')
        conn.execute('INSERT INTO logins (day, city, country, latitude, longitude, logins) VALUES (?, ?, ?, ?, ?, 1) '
                     'ON CONFLICT(day, city, country) DO UPDATE SET logins = logins + 1',
                     (day, city, country, latitude, longitude))
        conn.commit()
    finally:
        conn.close()


def countVisit(environ, now=None):
    """Counts the visit if it should be counted; True if it was. Never raises:
    a counting problem must not break the page."""
    try:
        if isBot(environ.get('HTTP_USER_AGENT')):
            return False
        address = clientAddress(environ)
        if address is None:
            return False
        place = lookupPlace(address)
        if place is None or seenRecently(address, now):
            return False
        recordVisit(place)
        return True
    except Exception as error:
        print(f'visit not counted: {type(error).__name__}', file=sys.stderr)   # never the address
        return False
