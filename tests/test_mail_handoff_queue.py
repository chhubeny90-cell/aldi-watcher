import pytest

import core.mail_handoff_queue as queue
from core.mail_actor_handoff import HandoffBlocked, Phase

KEY = "example-message-key"


@pytest.fixture
def memory(monkeypatch):
    state = {"sha": None, "events": {}}
    def load():
        return state["sha"], dict(state["events"])
    def persist(events, sha):
        if sha != state["sha"]:
            raise RuntimeError("github_aux_state_conflict")
        state["events"] = dict(events)
        state["sha"] = "version-" + str(len(state["events"])) + "-" + str(
            sum(record["revision"] for record in state["events"].values()))
    monkeypatch.setattr(queue, "_load", load)
    monkeypatch.setattr(queue, "_persist", persist)
    monkeypatch.setattr(queue, "_fingerprint", lambda value: "a" * 64)
    return state


def test_durable_reservation_and_duplicate(memory):
    assert queue.enqueue_consumed(KEY, "consumed") is True
    assert queue.enqueue_consumed(KEY, "consumed") is False
    assert len(memory["events"]) == 1


def test_warning_cannot_enqueue(memory):
    with pytest.raises(HandoffBlocked, match="not_consumed"):
        queue.enqueue_consumed(KEY, "80_percent")
    assert not memory["events"]


def test_write_failure_does_not_acknowledge(monkeypatch, memory):
    def fail(*_):
        raise RuntimeError("remote_unavailable")
    monkeypatch.setattr(queue, "_persist", fail)
    with pytest.raises(RuntimeError, match="remote_unavailable"):
        queue.enqueue_consumed(KEY, "consumed")


def test_inflight_crash_quarantines_and_prevents_replay(memory):
    queue.enqueue_consumed(KEY, "consumed")
    running = queue.update_event(KEY, 0, Phase.IN_FLIGHT)
    assert running.phase == Phase.IN_FLIGHT
    recovered = queue.quarantine_inflight_after_crash(KEY)
    assert recovered.phase == Phase.QUARANTINED_UNKNOWN
    with pytest.raises(HandoffBlocked, match="unsafe_transition"):
        queue.update_event(KEY, 2, Phase.IN_FLIGHT)


def test_stale_revision_blocks_transition(memory):
    queue.enqueue_consumed(KEY, "consumed")
    with pytest.raises(HandoffBlocked, match="stale_revision"):
        queue.update_event(KEY, 5, Phase.IN_FLIGHT)


def test_queue_capacity_fail_closed(monkeypatch):
    monkeypatch.setattr(queue, "_write_json", lambda *args, **kwargs: None)
    with pytest.raises(HandoffBlocked, match="queue_capacity_reached"):
        queue._persist({"a": {} , "b": {}}, None) if queue.MAX_EVENTS < 2 else queue._persist(
            {str(i): {} for i in range(queue.MAX_EVENTS + 1)}, None)
