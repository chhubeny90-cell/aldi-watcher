import json

import aldi_accounts_monitor as monitor


def test_auth_guard_is_clear_outside_github(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(monitor, "auth_backoff_active", lambda: True)
    assert monitor._auth_guard_status() == "clear"


def test_auth_guard_reports_active_on_github(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(monitor, "auth_backoff_active", lambda: True)
    assert monitor._auth_guard_status() == "active"


def test_auth_guard_fails_closed_when_state_is_unavailable(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def fail():
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(monitor, "auth_backoff_active", fail)
    assert monitor._auth_guard_status() == "unavailable"


def test_main_skips_manifest_and_browser_when_backoff_is_active(tmp_path, monkeypatch):
    report = tmp_path / "accounts.json"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("ALDI_ACCOUNTS_REPORT", str(report))
    monkeypatch.setattr(monitor, "auth_backoff_active", lambda: True)
    monkeypatch.setattr(
        monitor,
        "load_accounts",
        lambda: (_ for _ in ()).throw(AssertionError("manifest must not be loaded")),
    )

    assert monitor.main() == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "auth_backoff_active"
    assert payload["accounts"] == []
    assert payload["booking_executed"] is False


def test_main_fails_closed_before_manifest_when_guard_cannot_be_read(tmp_path, monkeypatch):
    report = tmp_path / "accounts.json"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("ALDI_ACCOUNTS_REPORT", str(report))

    def fail():
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(monitor, "auth_backoff_active", fail)
    monkeypatch.setattr(
        monitor,
        "load_accounts",
        lambda: (_ for _ in ()).throw(AssertionError("manifest must not be loaded")),
    )

    assert monitor.main() == 3
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "auth_guard_unavailable"
    assert payload["accounts"] == []
    assert payload["booking_executed"] is False
