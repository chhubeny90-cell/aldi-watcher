"""Durable, provider-free iPhone reminder outbox on the existing GitHub state branch.

Only keyed message fingerprints and delivery *attempt* phases are stored.
SMTP acceptance is not proof of message receipt or an ALDI booking.
"""
from github_hardening_state import _aux_path, _mac, _read_json, _write_json

VERSION = 1
MAX_EVENTS = 512
PHASES = frozenset({"READY", "SENDING", "SMTP_ACCEPTED", "UNKNOWN"})


def _fingerprint(message_key):
    if not isinstance(message_key, str) or not message_key or len(message_key) > 512:
        raise ValueError("invalid_notification_identity")
    return _mac("iphone-reminder-v1", message_key)


def _state():
    current = _read_json(_aux_path("iphone-notifications"))
    if current is None:
        return None, {}
    sha, payload = current
    events = payload.get("events")
    if payload.get("version") != VERSION or not isinstance(events, dict) or len(events) > MAX_EVENTS:
        raise RuntimeError("iphone_outbox_invalid")
    for key, item in events.items():
        if (not isinstance(key, str) or len(key) != 64
                or any(c not in "0123456789abcdef" for c in key)
                or not isinstance(item, dict) or set(item) != {"phase", "revision"}
                or item["phase"] not in PHASES
                or type(item["revision"]) is not int or item["revision"] < 0):
            raise RuntimeError("iphone_outbox_invalid")
    return sha, events


def _save(events, sha):
    if len(events) > MAX_EVENTS:
        raise RuntimeError("iphone_outbox_full")
    _write_json(_aux_path("iphone-notifications"),
                {"version": VERSION, "events": events}, sha,
                message="Persist manual iPhone refill notification outbox")


def enqueue(message_key):
    """Reserve a new notification before the mail cursor acknowledges the UID."""
    key = _fingerprint(message_key)
    for attempt in range(3):
        sha, events = _state()
        if key in events:
            return False
        if len(events) >= MAX_EVENTS:
            raise RuntimeError("iphone_outbox_full")
        updated = dict(events)
        updated[key] = {"phase": "READY", "revision": 0}
        try:
            _save(updated, sha)
            return True
        except RuntimeError as exc:
            if str(exc) != "github_aux_state_conflict" or attempt == 2:
                raise
    return False


def claim_one():
    """Commit SENDING before talking to SMTP; never retry an ambiguous attempt."""
    for attempt in range(3):
        sha, events = _state()
        ready = next((key for key, item in events.items() if item["phase"] == "READY"), None)
        if ready is None:
            return None
        updated = dict(events)
        item = updated[ready]
        updated[ready] = {"phase": "SENDING", "revision": item["revision"] + 1}
        try:
            _save(updated, sha)
            return ready
        except RuntimeError as exc:
            if str(exc) != "github_aux_state_conflict" or attempt == 2:
                raise
    return None


def finish(key, phase):
    if phase not in {"SMTP_ACCEPTED", "UNKNOWN"}:
        raise ValueError("invalid_delivery_phase")
    for attempt in range(3):
        sha, events = _state()
        item = events.get(key)
        if item is None or item["phase"] != "SENDING":
            raise RuntimeError("notification_not_in_flight")
        updated = dict(events)
        updated[key] = {"phase": phase, "revision": item["revision"] + 1}
        try:
            _save(updated, sha)
            return
        except RuntimeError as exc:
            if str(exc) != "github_aux_state_conflict" or attempt == 2:
                raise
