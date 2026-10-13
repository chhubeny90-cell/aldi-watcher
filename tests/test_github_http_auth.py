import requests
import pytest

import github_http_auth as auth
from core.aldi_http_login import LoginError


class FakeDriver:
    def __init__(self):
        self.calls = []

    def execute_cdp_cmd(self, command, payload):
        self.calls.append((command, payload))
        if command == "Network.setCookie":
            return {"success": True}
        return {}


class FakeClient:
    def __init__(self, cookies, error=None, indications=None):
        self.session = type("Session", (), {"cookies": cookies})()
        self.error = error
        self.report = {"provider_indications": indications or {}}
        self.login_calls = []
        self.closed = False

    def login(self, user, password):
        self.login_calls.append((user, password))
        if self.error:
            raise LoginError(self.error)
        return True

    def close(self):
        self.closed = True


def _jar(*cookies):
    jar = requests.cookies.RequestsCookieJar()
    for cookie in cookies:
        jar.set_cookie(cookie)
    return jar


def _cookie(name="session", value="private", domain="www.alditalk-kundenportal.de", path="/"):
    return requests.cookies.create_cookie(name=name, value=value, domain=domain, path=path, secure=True)


def test_cookie_handoff_injects_only_trusted_aldi_domains():
    driver = FakeDriver()
    jar = _jar(
        _cookie(),
        _cookie(name="login", domain="login.alditalk-kundenbetreuung.de"),
        _cookie(name="evil", domain="attacker.invalid"),
    )

    assert auth.inject_verified_cookies(driver, jar) == 2
    set_calls = [payload for command, payload in driver.calls if command == "Network.setCookie"]
    assert len(set_calls) == 2
    assert all("alditalk-" in payload["url"] for payload in set_calls)
    assert all("attacker.invalid" not in payload["url"] for payload in set_calls)


def test_cookie_handoff_requires_portal_cookie():
    driver = FakeDriver()
    jar = _jar(_cookie(domain="login.alditalk-kundenbetreuung.de"))

    with pytest.raises(LoginError, match="portal_session_cookie_missing"):
        auth.inject_verified_cookies(driver, jar)


def test_http_login_handoff_verifies_chrome_session(monkeypatch):
    driver = FakeDriver()
    client = FakeClient(_jar(_cookie()))
    monkeypatch.setattr(auth, "AldiHttpLogin", lambda: client)
    monkeypatch.setattr(auth.watcher, "ALDI_USER", "01520000000")
    monkeypatch.setattr(auth.watcher, "ALDI_PASS", "private-password")
    navigations = []
    monkeypatch.setattr(auth.watcher, "navigate", lambda driver, url, attempts=1: navigations.append((url, attempts)))
    monkeypatch.setattr(auth.watcher, "aldi_session_visible", lambda driver: True)

    assert auth.login_with_http_session(driver) is True
    assert auth.last_auth_outcome() == "ok"
    assert len(client.login_calls) == 1
    assert navigations == [(auth.watcher.ALDI_OVERVIEW_URL, 2)]
    assert client.closed is True


def test_http_login_lock_is_classified_without_second_submit(monkeypatch):
    driver = FakeDriver()
    client = FakeClient(
        _jar(),
        error="account_locked",
        indications={"account_locked": True},
    )
    monkeypatch.setattr(auth, "AldiHttpLogin", lambda: client)
    monkeypatch.setattr(auth.watcher, "ALDI_USER", "01520000000")
    monkeypatch.setattr(auth.watcher, "ALDI_PASS", "private-password")

    assert auth.login_with_http_session(driver) is False
    assert auth.last_auth_outcome() == "account_locked"
    assert len(client.login_calls) == 1
    assert not [call for call in driver.calls if call[0] == "Network.setCookie"]
    assert client.closed is True


def test_unverified_chrome_session_fails_closed(monkeypatch):
    driver = FakeDriver()
    client = FakeClient(_jar(_cookie()))
    monkeypatch.setattr(auth, "AldiHttpLogin", lambda: client)
    monkeypatch.setattr(auth.watcher, "ALDI_USER", "01520000000")
    monkeypatch.setattr(auth.watcher, "ALDI_PASS", "private-password")
    monkeypatch.setattr(auth.watcher, "navigate", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth.watcher, "aldi_session_visible", lambda driver: False)

    assert auth.login_with_http_session(driver) is False
    assert auth.last_auth_outcome() == "auth_failed"
    assert len(client.login_calls) == 1
