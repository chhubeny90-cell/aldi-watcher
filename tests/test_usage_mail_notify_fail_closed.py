import base64
import imaplib
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


@pytest.mark.parametrize("connection_only", [False, True])
def test_missing_dedup_key_fails_before_polling(monkeypatch, tmp_path, connection_only):
    path = _set_report(monkeypatch, tmp_path)
    monkeypatch.setattr(
        notify,
        "_mailboxes",
        lambda: [(1, "imap.example.invalid", 993, "user", "password")],
    )
    monkeypatch.delenv("ALDI_RECOVERY_KEY", raising=False)
    monkeypatch.delenv("ALDI_STATE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ALDI_MAIL_CONNECTION_ONLY", str(connection_only).lower())
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
    assert report["connection_only"] is connection_only
    assert report["mailbox_connectivity"][0]["readonly_inbox_ok"] is True


@pytest.mark.parametrize("failed_stage", [None, "login", "select"])
def test_connection_only_checks_all_mailboxes_without_processing_or_state(
        monkeypatch, tmp_path, capsys, failed_stage):
    monkeypatch.chdir(tmp_path)
    path = _set_report(monkeypatch, tmp_path)
    monkeypatch.setenv("ALDI_MAIL_CONNECTION_ONLY", "true")
    monkeypatch.setenv("ALDI_IPHONE_NOTIFY_ENABLED", "true")
    monkeypatch.delenv("ALDI_RECOVERY_KEY", raising=False)
    encoded_key = base64.urlsafe_b64encode(b"t" * 32).decode("ascii")
    monkeypatch.setenv("ALDI_STATE_ENCRYPTION_KEY", encoded_key)
    monkeypatch.setattr(notify, "_mailboxes", lambda: [
        (1, "imap.example.invalid", 993, "private-one", "private-password"),
        (2, "imap.example.invalid", 993, "private-two", "private-password"),
    ])
    calls = []

    def forbidden(*args, **kwargs):
        pytest.fail("Connection-only mode must not process messages or access durable state")

    for name in ("_poll_one", "_notification_seen", "claim_trigger_key",
                 "enqueue_consumed", "MailboxCursor"):
        monkeypatch.setattr(notify, name, forbidden)
    monkeypatch.setattr(notify.iphone_notification_outbox, "enqueue", forbidden)
    monkeypatch.setattr(notify.handoff_queue, "_load", forbidden)
    monkeypatch.setattr(notify.handoff_queue, "_archive", forbidden)

    class ConnectionOnlyInbox:
        def __init__(self, *args, **kwargs):
            assert kwargs["timeout"] == 20

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append((self.user, "logout"))
            return False

        def login(self, user, password):
            self.user = user
            calls.append((user, "login"))
            if user == "private-two" and failed_stage == "login":
                raise imaplib.IMAP4.error("PRIVATE_SERVER_ERROR")
            return "OK", []

        def select(self, name, readonly):
            assert name == "INBOX" and readonly is True
            calls.append((self.user, "readonly_inbox"))
            if self.user == "private-two" and failed_stage == "select":
                return "NO", [b"PRIVATE_SERVER_ERROR"]
            return "OK", []

        uid = search = fetch = forbidden

    monkeypatch.setattr(notify.imaplib, "IMAP4_SSL", ConnectionOnlyInbox)
    assert notify.main() == (2 if failed_stage else 0)
    report = json.loads(path.read_text())
    assert report["connection_only"] is True
    assert report["dedup_key_configured"] is True
    assert report["dedup_key_source"] == "state_key"
    assert report["configuration_error"] is None
    assert report["configured_mailboxes"] == 2
    assert len(report["mailbox_connectivity"]) == 2
    assert report["mailbox_connectivity"][0]["readonly_inbox_ok"] is True
    second = report["mailbox_connectivity"][1]
    assert second["login_ok"] is (failed_stage != "login")
    assert second["readonly_inbox_ok"] is (failed_stage is None)
    assert second["error"] == ("IMAPError" if failed_stage else None)
    assert len(report["failed_mailboxes"]) == (1 if failed_stage else 0)
    assert all(item["message_processing"] is False
               for item in report["mailbox_connectivity"])
    assert report["mailbox_scans"] == report["alerts"] == []
    assert report["new_alerts"] == report["actionable_alerts"] == 0
    assert report["provider_action"] is False
    assert report["booking_authorized"] is False
    assert report["provider_check_requested"] is False
    assert len([call for call in calls if call[1] == "login"]) == 2
    assert len([call for call in calls if call[1] == "logout"]) == 2
    assert list(tmp_path.iterdir()) == [path]
    serialized = path.read_text() + capsys.readouterr().out
    for private_value in (encoded_key, "PRIVATE_SERVER_ERROR", "private-one",
                          "private-two", "private-password", "imap.example.invalid"):
        assert private_value not in serialized


def test_connection_only_rejects_malformed_state_key_before_probe(monkeypatch, tmp_path):
    path = _set_report(monkeypatch, tmp_path)
    monkeypatch.setenv("ALDI_MAIL_CONNECTION_ONLY", "true")
    monkeypatch.delenv("ALDI_RECOVERY_KEY", raising=False)
    monkeypatch.setenv("ALDI_STATE_ENCRYPTION_KEY", "invalid-private-state-key")
    monkeypatch.setattr(notify, "_mailboxes", lambda: pytest.fail("Key validation must precede mailbox access"))
    monkeypatch.setattr(notify, "_probe_one", lambda *args: pytest.fail("Probe with invalid key"))

    assert notify.main() == 2
    report = json.loads(path.read_text())
    assert report["connection_only"] is True
    assert report["configuration_error"] == "state_dedup_key_invalid"
    assert report["mailbox_connectivity"] == []
    assert report["alerts"] == []
    assert "invalid-private-state-key" not in path.read_text()


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


def test_mail_and_smtp_secrets_are_scoped_to_separate_steps():
    text = Path(".github/workflows/mail-trigger.yml").read_text(encoding="utf-8")
    before, poller = text.split("      - name: Poll usage mailboxes without ALDI portal access\n", 1)
    poller, sender = poller.split("      - name: Deliver queued iPhone refill reminders (no provider action)\n", 1)
    sender, after = sender.split("      - name: Preserve sanitized usage-alert report\n", 1)
    assert "secrets." not in before and "secrets." not in after
    assert "ALDI_STATE_ENCRYPTION_KEY: ${{ secrets.ALDI_STATE_ENCRYPTION_KEY }}" in poller
    assert "MAILBOX_1_PASS: ${{ secrets.MAILBOX_1_PASS }}" in poller
    assert "ALDI_NOTIFY_SMTP_PASS" not in poller
    assert "ALDI_NOTIFY_SMTP_PASS: ${{ secrets.ALDI_NOTIFY_SMTP_PASS }}" in sender
    assert "MAILBOX_1_PASS" not in sender
    assert "ALDI_STATE_ENCRYPTION_KEY" not in sender
    assert "ALDI_PASS" not in text and "ALDI_USER:" not in text
    assert "vars.ALDI_IPHONE_NOTIFY_ENABLED == 'true'" in sender


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
