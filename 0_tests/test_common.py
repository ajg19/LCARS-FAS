"""Tests for scripts/common.py -- the .env loader, httpGet and the
Space-Track client. urllib is replaced by stand-ins; nothing touches the
network, and the real .env / spacetrack.env are never read."""

import io
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import common  # noqa: E402


class FakeResponse:
    def __init__(self, body=b'', status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeUrlopen:
    """Records each request and answers from a list of responses (or
    raises them, for HTTPError / URLError)."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def httpError(code, body=b''):
    return urllib.error.HTTPError('https://x', code, 'error', {}, io.BytesIO(body))


# --- loadDotenv --------------------------------------------------------------------

def test_dotenv_sets_variables_and_skips_comments(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('# a comment\n\nFAS_TEST_A = 1\nFAS_TEST_B=two=parts\nnot a setting\n', encoding='utf-8')
    for key in ('FAS_TEST_A', 'FAS_TEST_B'):
        monkeypatch.delenv(key, raising=False)
    common.loadDotenv(str(env))
    assert os.environ['FAS_TEST_A'] == '1'
    assert os.environ['FAS_TEST_B'] == 'two=parts'


def test_dotenv_never_overrides_the_environment(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('CELESTRAK_ENABLED=1\n', encoding='utf-8')
    monkeypatch.setenv('CELESTRAK_ENABLED', '0')
    common.loadDotenv(str(env))
    assert os.environ['CELESTRAK_ENABLED'] == '0'


def test_missing_dotenv_is_fine(tmp_path):
    common.loadDotenv(str(tmp_path / 'absent.env'))


# --- httpGet -----------------------------------------------------------------------

def test_http_get_returns_status_and_text_with_user_agent_and_timeout(monkeypatch):
    fake = FakeUrlopen(FakeResponse('héllo'.encode('utf-8')))
    monkeypatch.setattr(common.urllib.request, 'urlopen', fake)
    assert common.httpGet('https://example.test/x', {'Accept': 'application/json'}) == (200, 'héllo')
    request, timeout = fake.requests[0]
    assert request.get_header('User-agent') == common.USER_AGENT
    assert request.get_header('Accept') == 'application/json'
    assert timeout == common.HTTP_TIMEOUT_SEC


def test_http_errors_come_back_as_responses(monkeypatch):
    monkeypatch.setattr(common.urllib.request, 'urlopen', FakeUrlopen(httpError(503, b'busy')))
    assert common.httpGet('https://example.test/x') == (503, 'busy')


def test_connection_failures_still_raise(monkeypatch):
    monkeypatch.setattr(common.urllib.request, 'urlopen', FakeUrlopen(urllib.error.URLError('refused')))
    with pytest.raises(urllib.error.URLError):
        common.httpGet('https://example.test/x')


# --- SpaceTrack --------------------------------------------------------------------

@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setattr(common, 'loadProjectEnv', lambda: None)   # never the real spacetrack.env
    monkeypatch.setenv('SPACETRACK_USER', 'user@example.test')
    monkeypatch.setenv('SPACETRACK_PASS', 'secret')


def test_not_configured_without_credentials(monkeypatch):
    monkeypatch.setattr(common, 'loadProjectEnv', lambda: None)
    monkeypatch.delenv('SPACETRACK_USER', raising=False)
    monkeypatch.delenv('SPACETRACK_PASS', raising=False)
    assert not common.SpaceTrack().configured


def test_session_logs_in_queries_with_cookie_and_logs_out(credentials, monkeypatch):
    fake = FakeUrlopen(FakeResponse(b'""', headers={'Set-Cookie': 'chocolatechip=abc; path=/'}),
                       FakeResponse(b'[{"NORAD_CAT_ID": "25544"}]'),
                       FakeResponse(b''))
    monkeypatch.setattr(common.urllib.request, 'urlopen', fake)
    with common.SpaceTrack() as st:
        status, text = st.get('/basicspacedata/query/class/gp/NORAD_CAT_ID/25544/format/json')
    assert (status, text) == (200, '[{"NORAD_CAT_ID": "25544"}]')
    login, query, logout = (r for r, _ in fake.requests)
    assert login.get_method() == 'POST' and login.full_url.endswith('/ajaxauth/login')
    assert b'identity=user%40example.test' in login.data
    assert query.get_header('Cookie') == 'chocolatechip=abc'
    assert logout.full_url.endswith('/ajaxauth/logout')
    assert st.cookie is None


def test_rejected_credentials_raise(credentials, monkeypatch):
    monkeypatch.setattr(common.urllib.request, 'urlopen', FakeUrlopen(
        FakeResponse(b'{"Login":"Failed"}', headers={'Set-Cookie': 'x=y'})))
    with pytest.raises(Exception, match='rejected'):
        common.SpaceTrack().login()


def test_login_without_cookie_raises(credentials, monkeypatch):
    monkeypatch.setattr(common.urllib.request, 'urlopen', FakeUrlopen(FakeResponse(b'""')))
    with pytest.raises(Exception, match='session cookie'):
        common.SpaceTrack().login()


def test_login_http_error_raises(credentials, monkeypatch):
    monkeypatch.setattr(common.urllib.request, 'urlopen', FakeUrlopen(httpError(401)))
    with pytest.raises(Exception, match='HTTP 401'):
        common.SpaceTrack().login()


def test_failed_logout_never_fails_a_run(credentials, monkeypatch):
    fake = FakeUrlopen(FakeResponse(b'""', headers={'Set-Cookie': 'c=1'}), urllib.error.URLError('gone'))
    monkeypatch.setattr(common.urllib.request, 'urlopen', fake)
    with common.SpaceTrack():
        pass
    assert len(fake.requests) == 2
