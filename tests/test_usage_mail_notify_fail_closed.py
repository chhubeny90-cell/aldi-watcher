import json
from pathlib import Path

import usage_mail_notify as notify


def _set_report(monkeypatch, tmp_path):
    path = tmp_path / "usage-report.json"
    monkeypatch.setattr(notify, "REPORT_PATH", str(path))
    return path


def test_no_mailboxes_is_a_configuration_failure(monkeypatch, tmp_path):
    path = _set_report(monkeypatch, tmp_path)
    monkeypatch.setattr(notify, "_mailboxes", lambda: [])
    monkeypatch.delenv("ALDI_RECOVERY_KEY", raising=False)

    assert notify.main() == 2
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["configured_mailboxes"] == 0
    assert report["configuration_error"] == "no_mailboxes_configured"
    assert report["authenticated_portal"] is False
    assert report["provider_action"] is False


def test_missing_dedup_key_fails_before_polling(monkeypatch, tmp_path):
    path = _set_report(monkeypatch, tmp_path)
    monkeypatch.setattr(
        notify,
        "_mailboxes",
        lambda: [(1, "imap.example.invalid", 993, "user", "password")],
    )
    monkeypatch.delenv("ALDI_RECOVERY_KEY", raising=False)
    polls = []
    monkeypatch.setattr(notify, "_poll_one", lambda *args, **kwargs: polls.append(args) or [])

    assert notify.main() == 2
    assert polls == []
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["configured_mailboxes"] == 1
    assert report["dedup_key_configured"] is False
    assert report["configuration_error"] == "dedup_key_missing"


def test_workflow_surfaces_monitor_configuration_errors():
    text = Path(".github/workflows/mail-trigger.yml").read_text(encoding="utf-8")
    assert "config_error = report.get('configuration_error')" in text
    assert "Monitor configuration incomplete" in text
    assert "ALDI_PASS" not in text
    assert "github_live_refill" not in text
