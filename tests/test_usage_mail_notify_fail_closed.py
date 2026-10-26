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
    probes = []
    monkeypatch.setattr(notify, "_probe_one", lambda *args: probes.append(args) or {
        "mailbox": 1, "login_ok": True, "readonly_inbox_ok": True,
        "message_processing": False, "error": None,
    })

    assert notify.main() == 2
    assert polls == []
    assert len(probes) == 1
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["configured_mailboxes"] == 1
    assert report["dedup_key_configured"] is False
    assert report["configuration_error"] == "dedup_key_missing"
    assert report["mailbox_connectivity"][0]["readonly_inbox_ok"] is True


def test_workflow_surfaces_monitor_configuration_errors():
    text = Path(".github/workflows/mail-trigger.yml").read_text(encoding="utf-8")
    assert "config_error = report.get('configuration_error')" in text
    assert "Monitor configuration incomplete" in text
    assert "ALDI_PASS" not in text
    assert "github_live_refill" not in text


def test_workflow_keeps_dedup_key_independent_of_rotating_mailbox_passwords():
    text = Path(".github/workflows/mail-trigger.yml").read_text(encoding="utf-8")
    key_line = next(line.strip() for line in text.splitlines()
                    if line.strip().startswith("ALDI_RECOVERY_KEY:"))
    assert key_line == "ALDI_RECOVERY_KEY: ${{ secrets.ALDI_RECOVERY_KEY }}"


def test_mail_and_session_secrets_are_only_given_to_the_poller():
    text = Path(".github/workflows/mail-trigger.yml").read_text(encoding="utf-8")
    before, poller = text.split("      - name: Poll usage mailboxes without ALDI portal access\n", 1)
    poller, after = poller.split("      - name: Preserve sanitized usage-alert report\n", 1)
    assert "secrets." not in before and "secrets." not in after
    assert "ALDI_STATE_ENCRYPTION_KEY: ${{ secrets.ALDI_STATE_ENCRYPTION_KEY }}" in poller
    assert "MAILBOX_1_PASS: ${{ secrets.MAILBOX_1_PASS }}" in poller
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in poller


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
