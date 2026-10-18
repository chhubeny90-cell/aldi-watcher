"""Fail-closed durable handoff contract for ALDI consumed-mail events.

This module never launches a provider action. The caller must persist transitions
with compare-and-set (CAS) on the shared remote state before acknowledging them.
"""
from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    RESERVED = "RESERVED"
    IN_FLIGHT = "IN_FLIGHT"
    COMPLETED = "COMPLETED"
    QUARANTINED_UNKNOWN = "QUARANTINED_UNKNOWN"


class HandoffBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class Handoff:
    event_key: str
    phase: Phase
    revision: int = 0


def reserve(existing: Handoff | None, event_key: str, signal: str) -> Handoff:
    """Prepare a single event; caller must CAS-persist before acknowledging mail."""
    if signal != "consumed":
        raise HandoffBlocked("not_consumed")
    if not event_key or len(event_key) != 64 or any(c not in "0123456789abcdef" for c in event_key):
        raise HandoffBlocked("invalid_event_key")
    if existing is not None:
        raise HandoffBlocked("duplicate_or_unresolved_event")
    return Handoff(event_key, Phase.RESERVED)


def transition(current: Handoff, target: Phase, *, expected_revision: int) -> Handoff:
    """Require optimistic concurrency and prohibit automatic replay after uncertainty."""
    if current.revision != expected_revision:
        raise HandoffBlocked("stale_revision")
    allowed = {
        Phase.RESERVED: {Phase.IN_FLIGHT, Phase.QUARANTINED_UNKNOWN},
        Phase.IN_FLIGHT: {Phase.COMPLETED, Phase.QUARANTINED_UNKNOWN},
        Phase.COMPLETED: set(),
        Phase.QUARANTINED_UNKNOWN: set(),
    }
    # The provider has no implemented, operation-bound completion verifier.
    # Until such a verifier exists, a caller must never turn a mere volume
    # increase or a fabricated success flag into a terminal completion.
    if target == Phase.COMPLETED:
        raise HandoffBlocked("provider_receipt_verifier_unavailable")
    if target not in allowed[current.phase]:
        raise HandoffBlocked("unsafe_transition")
    return Handoff(current.event_key, target, current.revision + 1)


def recover_after_crash(current: Handoff) -> Handoff:
    """Never automatically re-run an action that might have reached the provider."""
    if current.phase == Phase.RESERVED:
        return current
    if current.phase == Phase.IN_FLIGHT:
        return transition(current, Phase.QUARANTINED_UNKNOWN, expected_revision=current.revision)
    return current
