from email.message import EmailMessage

import pytest

import usage_mail_notify as monitor
from tests.mail_test_support import RescanningCursor


@pytest.fixture(autouse=True)
def mail_key(monkeypatch):
    monkeypatch.setenv("ALDI_RECOVERY_KEY", "synthetic-test-key")
    monkeypatch.setattr(monitor, 'MailboxCursor', RescanningCursor)


class FakeImap:
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def login(self, *args):
        return "OK", []
    def select(self, *args, **kwargs):
        return "OK", []
    def uid(self, command, *args):
        if command == "search":
            return self.search(*args)
        assert command == "fetch" and args[1] == "(BODY.PEEK[])"
        return self.fetch(*args)
    def search(self, *args):
        return "OK", [b"1"]
    def fetch(self, *args):
        msg = EmailMessage()
        msg["From"] = "ALDI TALK <noreply@alditalk-kundenbetreuung.de>"
        msg["Subject"] = "Datenvolumen aufgebraucht"
        msg["Message-ID"] = "<unit-test@example.invalid>"
        msg.set_content("Ihr Datenvolumen ist aufgebraucht.")
        return "OK", [(b"1", msg.as_bytes())]


def test_consumed_mail_is_queued_not_legacy_claimed(monkeypatch):
    monkeypatch.setattr(monitor.imaplib, "IMAP4_SSL", FakeImap)
    queued = []
    def forbidden_claim(*args):
        raise AssertionError("legacy claim must not consume actionable mail")
    alerts = monitor._poll_one(
        1, "imap.example.invalid", 993, "user", "pass",
        claim=forbidden_claim,
        enqueue=lambda key, signal, **kwargs: queued.append((key, signal)) or True,
    )
    assert len(queued) == 1
    assert queued[0][1] == "consumed"
    assert len(alerts) == 1 and alerts[0]["actionable"] is True


def test_queue_failure_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(monitor.imaplib, "IMAP4_SSL", FakeImap)
    def failed_queue(*args, **kwargs):
        raise RuntimeError("remote_state_unavailable")
    try:
        monitor._poll_one(
            1, "imap.example.invalid", 993, "user", "pass",
            claim=lambda *_: True, enqueue=failed_queue,
        )
    except RuntimeError as exc:
        assert str(exc) == "remote_state_unavailable"
    else:
        raise AssertionError("failed durable enqueue must abort")
