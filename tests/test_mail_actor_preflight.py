import mail_actor_preflight as worker
import pytest


@pytest.fixture(autouse=True)
def snapshot(monkeypatch):
    # Unit fixtures supply one already-coherent immutable snapshot.
    monkeypatch.setattr(worker, "_load", lambda: (None, {}), raising=False)
    monkeypatch.setattr(worker, "_get_state", lambda: None, raising=False)
    monkeypatch.setattr(worker, "consistent_mail_snapshot", lambda: (
        "a" * 40, worker._load()[1], worker._get_state()))


def test_empty_queue_is_preflight_only(monkeypatch):
    monkeypatch.setattr(worker, "_get_state", lambda: ("sha", {"unresolved": []}))
    monkeypatch.setattr(worker, "_load", lambda: (None, {}))
    result = worker.preflight()
    assert result["status"] == "PREFLIGHT_ONLY"
    assert result["provider_action"] is False
    assert result["booking_enabled"] is False


def test_unresolved_event_blocks_preflight(monkeypatch):
    monkeypatch.setattr(worker, "_get_state", lambda: ("sha", {"unresolved": []}))
    monkeypatch.setattr(worker, "_load", lambda: (None, {
        "a" * 64: {"phase": "QUARANTINED_UNKNOWN", "revision": 2},
    }))
    result = worker.preflight()
    assert result["status"] == "BLOCKED"
    assert result["unknown"] == 1


def test_preflight_does_not_mutate_queue(monkeypatch):
    monkeypatch.setattr(worker, "_get_state", lambda: ("sha", {"unresolved": []}))
    def load():
        return "sha", {"a" * 64: {"phase": "RESERVED", "revision": 0}}
    monkeypatch.setattr(worker, "_load", load)
    result = worker.preflight()
    assert result["reserved"] == 1
    assert result["provider_action"] is False


def test_unresolved_provider_journal_blocks_handoff(monkeypatch):
    monkeypatch.setattr(worker, "_load", lambda: ("sha", {
        "a" * 64: {"phase": "RESERVED", "revision": 0},
    }))
    monkeypatch.setattr(worker, "_get_state", lambda: ("sha", {
        "unresolved": [{"recharge_id": "00000000-0000-4000-8000-000000000001",
                        "status": "UNKNOWN"}],
    }))
    result = worker.preflight()
    assert result["status"] == "BLOCKED"
    assert result["journal_unresolved"] == 1
    assert result["provider_action"] is False


def test_missing_remote_journal_blocks_handoff(monkeypatch):
    monkeypatch.setattr(worker, "_load", lambda: (None, {}))
    monkeypatch.setattr(worker, "_get_state", lambda: None)
    result = worker.preflight()
    assert result["status"] == "BLOCKED"
    assert result["journal_state_present"] is False
    assert result["journal_binding_verified"] is False


def test_blocked_preflight_returns_failing_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(worker, "preflight", lambda: {
        "status": "BLOCKED", "booking_enabled": False,
    })
    assert worker.main() == 2
    assert '"status": "BLOCKED"' in capsys.readouterr().out


def test_preflight_only_exit_is_not_booking_permission(monkeypatch, capsys):
    monkeypatch.setattr(worker, "preflight", lambda: {
        "status": "PREFLIGHT_ONLY", "booking_enabled": False,
    })
    assert worker.main() == 0
    assert '"booking_enabled": false' in capsys.readouterr().out
