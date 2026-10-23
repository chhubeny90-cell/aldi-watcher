"""Offline, credential-free diagnostics for distinct ALDI and LIDL public entry points.

No real browser, network call, provider password, account login or refill is used.
"""
import json
from unittest.mock import Mock

import pytest

import portal_probe
import watcher


@pytest.mark.parametrize(
    "provider,url,status",
    [
        ("lidl_connect", watcher.LIDL_LOGIN_URL, 403),
        ("aldi_talk", watcher.ALDI_LOGIN_URL, 200),
    ],
)
def test_public_probe_never_treats_http_status_as_authenticated(monkeypatch, provider, url, status):
    browser = Mock()
    browser.current_url = url
    browser.execute_script.return_value = "complete"
    browser.find_elements.return_value = []
    browser.find_element.return_value.text = "Zugriff verweigert" if status == 403 else "Anmelden"
    events = [
        {"message": json.dumps({"message": {
            "method": "Network.responseReceived",
            "params": {"type": "Document", "response": {"status": status, "url": url}},
        }})}
    ]
    browser.get_log.side_effect = lambda name: events if name == "performance" else []
    monkeypatch.setattr(portal_probe, "build_driver", lambda: browser)
    monkeypatch.setattr(portal_probe.time, "sleep", lambda _: None)

    result = portal_probe.probe(provider, url)

    browser.get.assert_called_once_with(url)
    browser.quit.assert_called_once()
    assert result["provider"] == provider
    assert result["status"] == "complete"  # Diagnostics completed; NOT account login.
    assert result["visible_input_types"] == []
    assert "login_ok" not in result
    assert "booking_executed" not in result
    if status == 403:
        assert "access_denied" in result["page_markers"]
        assert any(e.get("status") == 403 for e in result["resource_failures"])
    else:
        assert "login" in result["page_markers"]


@pytest.mark.parametrize("provider", ["aldi_talk", "lidl_connect"])
def test_public_diagnostics_do_not_continue_after_browser_error(monkeypatch, provider):
    browser = Mock()
    browser.get.side_effect = RuntimeError("SECRET_ACCOUNT_DATA")
    monkeypatch.setattr(portal_probe, "build_driver", lambda: browser)
    result = portal_probe.probe(provider, "https://example.invalid/")
    browser.quit.assert_called_once()
    assert result["status"] == "failed"
    assert result["error_type"] == "RuntimeError"
    assert "SECRET_ACCOUNT_DATA" not in json.dumps(result)


@pytest.mark.parametrize("secret", ["ALDI_USER", "ALDI_PASS", "LIDL_USER", "LIDL_PASS"])
def test_public_probe_refuses_plaintext_provider_credentials(monkeypatch, secret):
    for key in ("ALDI_USER", "ALDI_PASS", "LIDL_USER", "LIDL_PASS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(secret, "NOT_FOR_PROBES")
    monkeypatch.setattr(portal_probe, "probe", Mock(side_effect=AssertionError("network must not run")))
    with pytest.raises(RuntimeError, match="without provider credentials"):
        portal_probe.main()


