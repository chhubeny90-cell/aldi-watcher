"""Preflight-only consumer for persisted mail handoffs.

This worker intentionally has no browser, provider credentials or booking entrypoint.
It reports queue readiness, and fails closed on malformed or unresolved state.
"""
import json
from collections import Counter

from core.mail_handoff_queue import _load
from core.mail_actor_handoff import Phase
from github_journal_state import _get_state


def preflight():
    """Inspect both durable stores; never imply that an actor is authorized."""
    _, events = _load()
    journal = _get_state()
    counts = Counter(record["phase"] for record in events.values())
    unresolved = counts[Phase.IN_FLIGHT.value] + counts[Phase.QUARANTINED_UNKNOWN.value]
    # Missing journal state is not an empty, trustworthy journal.
    journal_missing = journal is None
    journal_unresolved = (
        len(journal[1]["unresolved"]) if journal is not None else None
    )
    blocked = bool(unresolved or journal_missing or journal_unresolved)
    return {
        "status": "BLOCKED" if blocked else "PREFLIGHT_ONLY",
        "reserved": counts[Phase.RESERVED.value],
        "in_flight": counts[Phase.IN_FLIGHT.value],
        "unknown": counts[Phase.QUARANTINED_UNKNOWN.value],
        "completed": counts[Phase.COMPLETED.value],
        "journal_state_present": not journal_missing,
        "journal_unresolved": journal_unresolved,
        "provider_action": False,
        "booking_enabled": False,
        "journal_binding_verified": False,
        "account_binding_verified": False,
        "provider_completion_verified": False,
    }

if __name__ == "__main__":
    try:
        print(json.dumps(preflight(), sort_keys=True))
    except Exception:
        print(json.dumps({"status": "BLOCKED", "provider_action": False,
                          "booking_enabled": False, "error": "preflight_failed"}))
        raise SystemExit(2)
