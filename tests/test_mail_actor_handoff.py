import pytest

from core.mail_actor_handoff import (
    Handoff, HandoffBlocked, Phase, recover_after_crash, reserve, transition,
)

KEY = "a" * 64


def test_only_consumed_mail_can_reserve():
    with pytest.raises(HandoffBlocked, match="not_consumed"):
        reserve(None, KEY, "80_percent")
    assert reserve(None, KEY, "consumed").phase == Phase.RESERVED


def test_duplicate_consumed_mail_cannot_reserve_twice():
    existing = reserve(None, KEY, "consumed")
    with pytest.raises(HandoffBlocked, match="duplicate"):
        reserve(existing, KEY, "consumed")


def test_reject_invalid_event_key():
    with pytest.raises(HandoffBlocked, match="invalid_event_key"):
        reserve(None, "raw-message-id", "consumed")


def test_stale_parallel_worker_cannot_transition():
    pending = reserve(None, KEY, "consumed")
    with pytest.raises(HandoffBlocked, match="stale_revision"):
        transition(pending, Phase.IN_FLIGHT, expected_revision=1)


def test_crash_before_actor_is_resumable_but_after_actor_is_quarantined():
    pending = reserve(None, KEY, "consumed")
    assert recover_after_crash(pending) == pending
    in_flight = transition(pending, Phase.IN_FLIGHT, expected_revision=0)
    recovered = recover_after_crash(in_flight)
    assert recovered.phase == Phase.QUARANTINED_UNKNOWN
    with pytest.raises(HandoffBlocked, match="unsafe_transition"):
        transition(recovered, Phase.IN_FLIGHT, expected_revision=recovered.revision)


def test_completion_cannot_be_replayed():
    pending = reserve(None, KEY, "consumed")
    in_flight = transition(pending, Phase.IN_FLIGHT, expected_revision=0)
    with pytest.raises(HandoffBlocked, match="provider_receipt_verifier_unavailable"):
        transition(in_flight, Phase.COMPLETED, expected_revision=1)
    assert recover_after_crash(in_flight).phase == Phase.QUARANTINED_UNKNOWN


def test_cannot_claim_success_before_actor():
    pending = reserve(None, KEY, "consumed")
    with pytest.raises(HandoffBlocked, match="unsafe_transition"):
        transition(pending, Phase.COMPLETED, expected_revision=0)
