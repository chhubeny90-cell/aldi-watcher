"""Offline tests: persistent opt-in notification, dedup and crash uncertainty."""
import copy
import json
from email.message import EmailMessage

import pytest

from core import iphone_notification_outbox as outbox
from scripts import send_iphone_notifications as sender
import usage_mail_notify as monitor
from tests.mail_test_support import RescanningCursor


@pytest.fixture
def remote(monkeypatch):
    state = {"sha": None, "payload": None, "writes": 0}
    def read(_path):
        return (None if state["payload"] is None
                else (state["sha"], copy.deepcopy(state["payload"])))
    def write(_path, payload, sha, **_):
        if sha != state["sha"]:
            raise RuntimeError("github_aux_state_conflict")
        state["writes"] += 1
        state["sha"] = str(state["writes"])
        state["payload"] = copy.deepcopy(payload)
    monkeypatch.setenv("ALDI_RECOVERY_KEY", "synthetic-test-only")
    monkeypatch.setattr(outbox, "_read_json", read)
    monkeypatch.setattr(outbox, "_write_json", write)
    return state


def test_new_event_is_durable_and_once_only(remote):
    assert outbox.enqueue("a") is True
    assert outbox.enqueue("a") is False
    assert outbox.claim_one() is not None
    assert outbox.claim_one() is None
    assert list(remote["payload"]["events"].values())[0]["phase"] == "SENDING"


def test_smtp_acceptance_is_not_booking(remote):
    outbox.enqueue("a")
    key = outbox.claim_one()
    outbox.finish(key, "SMTP_ACCEPTED")
    assert outbox.claim_one() is None
    assert list(remote["payload"]["events"].values())[0]["phase"] == "SMTP_ACCEPTED"


def test_unknown_delivery_does_not_retry(remote, monkeypatch):
    outbox.enqueue("a")
    monkeypatch.setattr(sender, "_email_settings", lambda: ("test",))
    def failed(_):
        raise RuntimeError("private smtp text")
    monkeypatch.setattr(sender, "_send", failed)
    assert sender.drain()["ambiguous"] == 1
    assert outbox.claim_one() is None
    assert list(remote["payload"]["events"].values())[0]["phase"] == "UNKNOWN"


def test_missing_configuration_does_not_claim(remote, monkeypatch):
    outbox.enqueue("a")
    monkeypatch.delenv("ALDI_NOTIFY_SMTP_HOST", raising=False)
    with pytest.raises(RuntimeError, match="smtp_configuration_missing"):
        sender.drain()
    assert list(remote["payload"]["events"].values())[0]["phase"] == "READY"


def test_successful_smtp_attempt_only_accepts_message(remote, monkeypatch):
    outbox.enqueue("a")
    monkeypatch.setattr(sender, "_email_settings", lambda: ("test",))
    sends = []
    monkeypatch.setattr(sender, "_send", lambda setting: sends.append(setting))
    assert sender.drain() == {"smtp_accepted": 1, "ambiguous": 0}
    assert sends == [("test",)]
    assert list(remote["payload"]["events"].values())[0]["phase"] == "SMTP_ACCEPTED"


def test_corrupt_remote_state_aborts(monkeypatch):
    monkeypatch.setattr(outbox, "_read_json", lambda *_: ("sha", {
        "version": 1, "events": {"a" * 64: {"phase": [], "revision": 0}}
    }))
    with pytest.raises(RuntimeError, match="iphone_outbox_invalid"):
        outbox.claim_one()


class FakeImap:
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def login(self, *_):
        return "OK", []
    def select(self, *_, **__):
        return "OK", []
    def uid(self, command, *args):
        if command == "search":
            return "OK", [b"1"]
        assert command == "fetch"
        message = EmailMessage()
        message["From"] = "ALDI TALK <noreply@alditalk-kundenbetreuung.de>"
        message["Subject"] = "Datenvolumen aufgebraucht"
        message["Message-ID"] = "<safe-synthetic@example.invalid>"
        message.set_content("Ihr Datenvolumen ist aufgebraucht.")
        return "OK", [(b"1", message.as_bytes())]


def test_assisted_poll_enqueues_before_cursor_and_without_claim(monkeypatch, remote):
    monkeypatch.setenv("ALDI_IPHONE_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("ALDI_MAIL_TRIGGER_POLICY", "portal_check")
    monkeypatch.setattr(monitor, "MailboxCursor", RescanningCursor)
    monkeypatch.setattr(monitor.imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(monitor, "_notification_seen", lambda *_: False)
    def forbidden(*_):
        raise AssertionError("legacy claim must not run in assisted mode")
    first = monitor._poll_one(1, "imap.test", 993, "user", "pass", claim=forbidden)
    second = monitor._poll_one(1, "imap.test", 993, "user", "pass", claim=forbidden)
    assert len(first) == 1 and first[0]["actionable"]
    assert second == []
    assert len(remote["payload"]["events"]) == 1
