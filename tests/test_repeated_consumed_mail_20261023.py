"""Regression evidence: eight real-world same-body mails are not eight refills.

The 2026-10-21/22 reference corpus is intentionally metadata-only: no user
names, phone numbers, email addresses, or full message bodies in test fixtures.
These tests make the boundary explicit, not a claim of provider-cycle identity.
"""
from email.message import EmailMessage

import pytest

import usage_mail_bridge as bridge
import usage_mail_notify as monitor
from core.mail_actor_handoff import HandoffBlocked
import core.mail_handoff_queue as queue


TIMES_UTC = (
    "Wed, 21 Oct 2026 13:57:29 +0000",
    "Wed, 21 Oct 2026 14:05:24 +0000",
    "Wed, 21 Oct 2026 14:13:11 +0000",
    "Wed, 21 Oct 2026 14:25:37 +0000",
    "Wed, 21 Oct 2026 15:27:48 +0000",
    "Wed, 21 Oct 2026 16:14:43 +0000",
    "Wed, 21 Oct 2026 19:19:46 +0000",
    "Thu, 22 Oct 2026 02:07:04 +0000",
)


def _mail(index, body="Das Datenvolumen deines Tarifs oder einer Zusatz-Option ist verbraucht."):
    message = EmailMessage()
    message["From"] = "ALDI TALK <noreply@alditalk-kundenbetreuung.de>"
    message["To"] = "synthetic@example.invalid"
    message["Subject"] = "Verbrauch deines Datenvolumens"
    message["Date"] = TIMES_UTC[index]
    message["Message-ID"] = f"<synthetic-{index}@example.invalid>"
    message.set_content(body)
    return message


def test_eight_identical_100_percent_bodies_have_distinct_message_identities(monkeypatch):
    monkeypatch.setenv("ALDI_RECOVERY_KEY", "synthetic-only-test-key")
    messages = [_mail(i) for i in range(8)]
    assert all(bridge._signal(m) == "consumed" for m in messages)
    keys = [bridge._message_key(m, m.as_bytes()) for m in messages]
    assert len(set(keys)) == 8
    # Message dedupe cannot be used as provider-consumption-cycle proof.
    assert len({m.get_body(preferencelist=("plain",)).get_content()
                for m in messages}) == 1


def test_warning_not_eligible_for_handoff():
    with pytest.raises(HandoffBlocked, match="not_consumed"):
        queue.enqueue_consumed("synthetic", "80_percent")


def test_monitor_does_not_call_provider_for_consumed_messages(monkeypatch):
    """The monitor only enqueues; provider booking needs independent cycle proof."""
    class FakeIMAP:
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def login(self, *_args): pass
        def select(self, *_args, **_kwargs): return "OK", []
        def search(self, *_args): return "OK", [b"1 2 3 4 5 6 7 8"]
        def fetch(self, identifier, *_args):
            return "OK", [(b"BODY[]", _mail(int(identifier) - 1).as_bytes())]

    monkeypatch.setattr(monitor.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(monitor, "_message_key", lambda message, raw: message["Message-ID"])
    monkeypatch.setattr(monitor, "_legacy_message_key", lambda message, raw: "legacy:" + message["Message-ID"])
    seen = set()
    def enqueue(key, signal, *, legacy_message_key=None):
        if key in seen: return False
        seen.add(key)
        return True

    alerts = monitor._poll_one(1, "synthetic.invalid", 993, "synthetic", "synthetic",
                               enqueue=enqueue)
    assert len(alerts) == 8
    assert all(a["signal"] == "consumed" for a in alerts)
    # This demonstrates the missing cycle-level dedupe. These are candidates,
    # NOT eight independently authorized provider bookings.
    assert len(seen) == 8
