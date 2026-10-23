"""Fail-closed profile candidate state is durable, private and concurrency-safe."""
import pytest

import core.mail_cycle_guard as guard
from core.mail_actor_handoff import HandoffBlocked


@pytest.fixture
def remote(monkeypatch):
    state = {"sha": None, "profiles": {}, "writes": 0}
    monkeypatch.setattr(guard, "_mac", lambda label, value: ("a" if label.endswith("profile") else "b") * 64
                        if value in ("sim-A", "message-0") else
                        ("c" if label.endswith("profile") else "d") * 64)
    def load():
        return state["sha"], dict(state["profiles"])
    def persist(profiles, sha):
        if sha != state["sha"]:
            raise RuntimeError("github_aux_state_conflict")
        state["profiles"] = dict(profiles)
        state["writes"] += 1
        state["sha"] = str(state["writes"])
    monkeypatch.setattr(guard, "_load", load)
    monkeypatch.setattr(guard, "_persist", persist)
    return state


def test_eight_distinct_mails_only_one_unverified_candidate(remote):
    assert guard.reserve_unverified_candidate("sim-A", "message-0") is True
    assert [guard.reserve_unverified_candidate("sim-A", "message-" + str(i))
            for i in range(1, 8)] == [False] * 7
    assert len(remote["profiles"]) == 1
    assert remote["writes"] == 1


def test_separate_profile_is_not_deduped_together(remote):
    assert guard.reserve_unverified_candidate("sim-A", "message-0")
    assert guard.reserve_unverified_candidate("sim-B", "message-0")
    assert len(remote["profiles"]) == 2


def test_unknown_never_retries_even_after_different_mail(remote):
    assert guard.reserve_unverified_candidate("sim-A", "message-0")
    assert guard.quarantine_unknown("sim-A")
    assert not guard.quarantine_unknown("sim-A")
    assert not guard.reserve_unverified_candidate("sim-A", "new-message")
    assert next(iter(remote["profiles"].values()))["state"] == "UNKNOWN"


def test_missing_or_ambiguous_binding_fails_closed(remote):
    for invalid in (None, "", " ", " sim-A", "sim-A ", 123):
        with pytest.raises(HandoffBlocked, match="invalid_profile"):
            guard.reserve_unverified_candidate(invalid, "message-0")
    assert not remote["profiles"]


def test_remote_failure_cannot_claim_candidate(monkeypatch, remote):
    def fail(*args):
        raise RuntimeError("github_aux_read_only")
    monkeypatch.setattr(guard, "_persist", fail)
    with pytest.raises(RuntimeError, match="github_aux_read_only"):
        guard.reserve_unverified_candidate("sim-A", "message-0")
    assert not remote["profiles"]


def test_cas_conflict_reloads_and_dedupes(monkeypatch, remote):
    original = guard._persist
    attempts = [0]
    def concurrent(profiles, sha):
        if not attempts[0]:
            attempts[0] += 1
            original(profiles, sha)
            raise RuntimeError("github_aux_state_conflict")
        return original(profiles, sha)
    monkeypatch.setattr(guard, "_persist", concurrent)
    assert not guard.reserve_unverified_candidate("sim-A", "message-0")
    assert remote["writes"] == 1


def test_verified_cycle_not_supported_without_provider_evidence(remote):
    with pytest.raises(HandoffBlocked, match="provider_cycle_verifier_unavailable"):
        guard.reserve_verified_provider_cycle("sim-A", "some-cycle", "some-mail")
    assert not remote["profiles"]


def test_corrupt_remote_guard_fails_closed(monkeypatch):
    monkeypatch.setattr(guard, "_mac", lambda *_: "a" * 64)
    monkeypatch.setattr(guard, "_read_json", lambda *args: (
        "sha", {"version": 1, "profiles": {"invalid": {"state": "UNVERIFIED", "first_message": "a"*64}}}))
    with pytest.raises(HandoffBlocked, match="cycle_guard_invalid"):
        guard.reserve_unverified_candidate("sim-A", "message-0")


def test_profile_hmac_only_in_remote_record(monkeypatch):
    seen = {}
    monkeypatch.setattr(guard, "_mac", lambda label, value: ("a" if label.endswith("profile") else "b")*64)
    monkeypatch.setattr(guard, "_read_json", lambda path: None)
    monkeypatch.setattr(guard, "_write_json", lambda path, payload, sha, **kwargs: seen.update(payload))
    assert guard.reserve_unverified_candidate("synthetic-account", "synthetic-message")
    assert "synthetic-account" not in repr(seen)
    assert "synthetic-message" not in repr(seen)
