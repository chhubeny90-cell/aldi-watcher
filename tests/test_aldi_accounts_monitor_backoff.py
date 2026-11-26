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


def test_main_continues_after_invalid_number_and_failed_identity(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from core.aldi_accounts import validate_accounts

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("AUTO_BOOK_ENABLED", "false")
    report = tmp_path / "accounts.json"
    monkeypatch.setenv("ALDI_ACCOUNTS_REPORT", str(report))
    fake_watcher = SimpleNamespace(build_driver=object())
    monkeypatch.setitem(sys.modules, "watcher", fake_watcher)
    payload = {"version": 1, "accounts": [
        {"account_id": "account_a", "provider": "aldi_talk",
         "account_user": "invalid"},
        {"account_id": "account_b", "provider": "aldi_talk",
         "account_user": "+491500000001", "enabled": True, "password": "test-only"},
        {"account_id": "account_c", "provider": "aldi_talk",
         "account_user": "+491500000002", "enabled": True, "password": "test-only"},
    ]}
    monkeypatch.setattr(monitor, "load_accounts",
                        lambda *, skipped: validate_accounts(payload, skipped=skipped))
    seen = []

    def execute(provider, factory, login, read, run_id):
        seen.append(run_id.rsplit("-", 1)[-1])
        return {"status": "auth_failed" if len(seen) == 1 else "ok"}

    monkeypatch.setattr(monitor, "execute_provider", execute)
    assert monitor.main() == 1
    assert seen == ["account_b", "account_c"]
    result = json.loads(report.read_text(encoding="utf-8"))
    assert [entry["status"] for entry in result["accounts"]] == [
        "skipped", "auth_failed", "ok"]
    assert result["booking_executed"] is False
    assert "invalid_account_number" in report.read_text(encoding="utf-8")
    assert "+491500000001" not in report.read_text(encoding="utf-8")
