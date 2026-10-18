"""Preflight-only consumer for persisted mail handoffs.

This worker intentionally has no browser, provider credentials or booking entrypoint.
It reports queue readiness, and fails closed on malformed or unresolved state.
"""
import json
from collections import Counter

from core.mail_handoff_queue import _load
from core.mail_actor_handoff import Phase


def preflight():
    _, events = _load()
    counts = Counter(record["phase"] for record in events.values())
    unresolved = counts[Phase.IN_FLIGHT.value] + counts[Phase.QUARANTINED_UNKNOWN.value]
    return {
        "status": "BLOCKED" if unresolved else "PREFLIGHT_ONLY",
        "reserved": counts[Phase.RESERVED.value],
        "in_flight": counts[Phase.IN_FLIGHT.value],
        "unknown": counts[Phase.QUARANTINED_UNKNOWN.value],
        "completed": counts[Phase.COMPLETED.value],
        "provider_action": False,
        "booking_enabled": False,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(preflight(), sort_keys=True))
    except Exception:
        print(json.dumps({"status": "BLOCKED", "provider_action": False,
                          "booking_enabled": False, "error": "preflight_failed"}))
        raise SystemExit(2)
