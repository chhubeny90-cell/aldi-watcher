import mail_actor_preflight as worker
from core.mail_actor_handoff import HandoffBlocked


def test_empty_queue_is_preflight_only(monkeypatch):
    monkeypatch.setattr(worker, "_load", lambda: (None, {}))
    result = worker.preflight()
    assert result["status"] == "PREFLIGHT_ONLY"
    assert result["provider_action"] is False
    assert result["booking_enabled"] is False


def test_unresolved_event_blocks_preflight(monkeypatch):
    monkeypatch.setattr(worker, "_load", lambda: (None, {
        "a" * 64: {"phase": "QUARANTINED_UNKNOWN", "revision": 2},
    }))
    result = worker.preflight()
    assert result["status"] == "BLOCKED"
    assert result["unknown"] == 1


def test_preflight_does_not_mutate_queue(monkeypatch):
    def load():
        return "sha", {"a" * 64: {"phase": "RESERVED", "revision": 0}}
    monkeypatch.setattr(worker, "_load", load)
    result = worker.preflight()
    assert result["reserved"] == 1
    assert result["provider_action"] is False
