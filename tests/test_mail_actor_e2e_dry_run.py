"""Credential-free mail-to-journal integration tests. No provider login or booking."""
from email.message import EmailMessage

import pytest

import usage_mail_notify as monitor
from tests.mail_test_support import RescanningCursor
import mail_actor_preflight as preflight
import core.mail_handoff_queue as queue
from core.mail_actor_handoff import HandoffBlocked, Phase


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
        message = EmailMessage()
        message["From"] = "ALDI TALK <noreply@alditalk-kundenbetreuung.de>"
        message["Subject"] = "Datenvolumen aufgebraucht"
        message["Message-ID"] = "<safe-e2e-fixture@example.invalid>"
        message.set_content("Ihr ALDI TALK Datenvolumen ist aufgebraucht.")
        return "OK", [(b"1", message.as_bytes())]


@pytest.fixture
def remote_state(monkeypatch):
    monkeypatch.setenv("ALDI_RECOVERY_KEY", "synthetic-test-key")
    monkeypatch.setattr(monitor, 'MailboxCursor', RescanningCursor)
    monkeypatch.setattr(queue, "_archive", lambda: (None, {}))
    monkeypatch.setattr(queue, "_legacy_seen", lambda *args: False)
    state = {"sha": None, "events": {}}

    def load():
        return state["sha"], dict(state["events"])

    def persist(events, sha):
        if sha != state["sha"]:
            raise RuntimeError("github_aux_state_conflict")
        state["events"] = dict(events)
        state["sha"] = "rev-" + str(sum(
            event["revision"] + 1 for event in events.values()
        ))

    monkeypatch.setattr(queue, "_load", load)
    monkeypatch.setattr(queue, "_persist", persist)
    monkeypatch.setattr(queue, "_fingerprint", lambda _: "b" * 64)
    monkeypatch.setattr(monitor.imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(preflight, "_load", load, raising=False)
    monkeypatch.setattr(preflight, "_get_state", lambda: (
        "journal-sha", {"unresolved": []}
    ), raising=False)
    monkeypatch.setattr(preflight, "consistent_mail_snapshot", lambda: (
        "a" * 40, load()[1], preflight._get_state()))
    return state


def test_mail_to_durable_queue_to_journal_preflight_no_actor(remote_state):
    first = monitor._poll_one(
        1, "imap.example.invalid", 993, "fake", "fake",
        claim=lambda _: pytest.fail("legacy trigger used"),
        enqueue=queue.enqueue_consumed,
    )
    second = monitor._poll_one(
        1, "imap.example.invalid", 993, "fake", "fake",
        claim=lambda _: pytest.fail("legacy trigger used"),
        enqueue=queue.enqueue_consumed,
    )
    result = preflight.preflight()
    assert len(first) == 1 and first[0]["actionable"] is True
    assert second == []
    assert result["reserved"] == 1
    assert result["status"] == "PREFLIGHT_ONLY"
    assert result["booking_enabled"] is False
    assert result["provider_action"] is False
    assert result["provider_completion_verified"] is False


def test_crash_after_claim_cannot_be_replayed(remote_state):
    assert queue.enqueue_consumed("test-key", "consumed")
    queue.update_event("test-key", 0, Phase.IN_FLIGHT)
    assert preflight.preflight()["status"] == "BLOCKED"
    recovered = queue.quarantine_inflight_after_crash("test-key")
    assert recovered.phase == Phase.QUARANTINED_UNKNOWN
    with pytest.raises(HandoffBlocked, match="unsafe_transition"):
        queue.update_event("test-key", 2, Phase.IN_FLIGHT)
    with pytest.raises(HandoffBlocked, match="unsafe_transition"):
        queue.update_event("test-key", 2, Phase.COMPLETED)


def test_provider_journal_unknown_blocks_even_reserved_mail(remote_state, monkeypatch):
    assert queue.enqueue_consumed("test-key", "consumed")
    monkeypatch.setattr(preflight, "_get_state", lambda: (
        "journal-sha", {"unresolved": [{
            "recharge_id": "00000000-0000-4000-8000-000000000001",
            "status": "UNKNOWN",
        }]}
    ))
    result = preflight.preflight()
    assert result["status"] == "BLOCKED"
    assert result["journal_unresolved"] == 1
    assert result["booking_enabled"] is False
