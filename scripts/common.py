"""Helpers shared by the ingestion scripts: the .env loader, an HTTP GET
that always returns (status, body), and one Space-Track client.

Replaces the copies each ingestion script used to carry
(0_documentation/dbRefactorPlan.md, step 3). Standard library only,
matching the rest of the Python side.
"""

import os
import urllib.error
import urllib.parse
import urllib.request

from dbPaths import ROOT

# Every request identifies this project, so a source can see who is
# calling and how to reach us, rather than an anonymous "Python-urllib".
USER_AGENT = 'LCARS-FAS/1.0 (+https://github.com/ajg19/LCARS-FAS)'
# Give up instead of hanging on the OS's ~2-minute connect timeout.
HTTP_TIMEOUT_SEC = 60


def loadDotenv(path):
    """Minimal .env loader (no python-dotenv dependency). Only sets
    variables not already in the environment, like dotenv's default."""
    if not os.path.isfile(path):
        return
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip())


def loadProjectEnv():
    """The app's .env (CelesTrak etiquette etc.) and spacetrack.env (the
    Space-Track credentials, chmod 600, never deployed or committed)."""
    loadDotenv(os.path.join(ROOT, '.env'))
    loadDotenv(os.path.join(ROOT, 'spacetrack.env'))


def httpGet(url, headers=None, timeout=HTTP_TIMEOUT_SEC):
    """(status_code, body_text). urllib raises on 4xx/5xx; this returns
    those like any other response, so callers check the status (and can
    read an error body). Connection-level failures (refused, timed out,
    DNS) still raise urllib.error.URLError / socket.timeout."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')


SPACETRACK_BASE_URL = 'https://www.space-track.org'


class SpaceTrack:
    """One Space-Track session: logs in once, runs any number of queries,
    logs out. Use as a context manager:

        with SpaceTrack() as st:
            status, text = st.get('/basicspacedata/query/class/gp/...')

    `configured` is False when SPACETRACK_USER / SPACETRACK_PASS aren't
    set; callers skip their Space-Track pass in that case."""

    def __init__(self):
        loadProjectEnv()
        self.user = os.environ.get('SPACETRACK_USER')
        self.password = os.environ.get('SPACETRACK_PASS')
        self.cookie = None

    @property
    def configured(self):
        return bool(self.user and self.password)

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, *exc):
        self.logout()
        return False

    def login(self):
        body = urllib.parse.urlencode({'identity': self.user, 'password': self.password}).encode('utf-8')
        request = urllib.request.Request(
            SPACETRACK_BASE_URL + '/ajaxauth/login', data=body, method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SEC) as response:
                cookie = response.headers.get('Set-Cookie')
                text = response.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            raise Exception(f'Space-Track login failed: HTTP {e.code}')
        if 'Failed' in text:
            raise Exception('Space-Track login rejected (bad credentials)')
        if not cookie:
            raise Exception('Space-Track login did not return a session cookie')
        self.cookie = cookie.split(';')[0]

    def get(self, path):
        """(status_code, body_text) for a query path under the base URL."""
        return httpGet(SPACETRACK_BASE_URL + path, headers={'Cookie': self.cookie})

    def logout(self):
        if not self.cookie:
            return
        try:
            httpGet(SPACETRACK_BASE_URL + '/ajaxauth/logout', headers={'Cookie': self.cookie}, timeout=15)
        except Exception:
            pass  # the session expires on its own; never fail a run over this
        self.cookie = None
