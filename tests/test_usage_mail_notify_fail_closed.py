import json
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("index", [1, 2])
def test_partial_mailbox_configuration_is_reported_without_polling(monkeypatch, tmp_path, index):
    path = _set_report(monkeypatch, tmp_path)
    for number in (1, 2):
        for field in ("HOST", "USER", "PASS", "PORT"):
            monkeypatch.delenv(f"MAILBOX_{number}_{field}", raising=False)
    monkeypatch.setenv(f"MAILBOX_{index}_USER", "private-user@example.invalid")
    polls = []
    monkeypatch.setattr(notify, "_poll_one", lambda *args: polls.append(args))

    assert notify.main() == 2
    report = json.loads(path.read_text())
    assert report["configuration_error"] == f"mailbox_{index}_configuration_incomplete"
    assert polls == []
    assert "private-user" not in path.read_text()
    assert report["provider_action"] is False


def test_invalid_port_is_reported_without_echoing_configuration(monkeypatch, tmp_path):
    path = _set_report(monkeypatch, tmp_path)
    for field, value in {"HOST": "imap.example.invalid", "USER": "private-user",
                         "PASS": "private-password", "PORT": "private-invalid-port"}.items():
        monkeypatch.setenv(f"MAILBOX_1_{field}", value)
    polls = []
    monkeypatch.setattr(notify, "_poll_one", lambda *args: polls.append(args))

    assert notify.main() == 2
    assert json.loads(path.read_text())["configuration_error"] == "mailbox_configuration_invalid"
    assert "private-" not in path.read_text()
    assert polls == []
