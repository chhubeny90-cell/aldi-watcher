"""CAS-backed mail event queue. Never dispatches or invokes the provider.

Persist only keyed HMAC fingerprints; a crash after reserving an event is
recoverable without claiming it processed. Unknown in-flight work is quarantined.
"""
from core.mail_actor_handoff import Handoff, HandoffBlocked, Phase, recover_after_crash, reserve, transition
from github_hardening_state import _aux_path, _mac, _read_json, _write_json

QUEUE_VERSION = 1
MAX_EVENTS = 512


def _load():
    current = _read_json(_aux_path("mail-handoff"))
    if current is None:
        return None, {}
    sha, data = current
    events = data.get("events")
    if data.get("version") != QUEUE_VERSION or not isinstance(events, dict) or len(events) > MAX_EVENTS:
        raise HandoffBlocked("queue_invalid")
    for key, record in events.items():
        if (not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key) or
                not isinstance(record, dict) or set(record) != {"phase", "revision"} or
                type(record["phase"]) is not str or record["phase"] not in Phase._value2member_map_ or
                type(record["revision"]) is not int or record["revision"] < 0):
            raise HandoffBlocked("queue_invalid")
    return sha, events


def _persist(events, sha):
    if len(events) > MAX_EVENTS:
        raise HandoffBlocked("queue_capacity_reached")
    _write_json(_aux_path("mail-handoff"), {"version": QUEUE_VERSION, "events": events},
                sha, message="Persist ALDI mail handoff state")


def _fingerprint(message_key):
    if not isinstance(message_key, str) or not message_key or len(message_key) > 512:
        raise HandoffBlocked("invalid_message_key")
    return _mac("mail-handoff", message_key)


def enqueue_consumed(message_key, signal):
    """Return True only after the remote reservation has been committed."""
    if signal != "consumed":
        raise HandoffBlocked("not_consumed")
    key = _fingerprint(message_key)
    for attempt in range(2):
        sha, events = _load()
        existing = events.get(key)
        if existing is not None:
            return False
        reservation = reserve(None, key, signal)
        updated = dict(events)
        updated[key] = {"phase": reservation.phase.value, "revision": reservation.revision}
        try:
            _persist(updated, sha)
            return True
        except RuntimeError as exc:
            if str(exc) != "github_aux_state_conflict" or attempt:
                raise
    raise HandoffBlocked("reservation_unconfirmed")


def update_event(message_key, expected_revision, target):
    """Transition an existing event with CAS; never silently replay a stale worker."""
    key = _fingerprint(message_key)
    sha, events = _load()
    record = events.get(key)
    if record is None:
        raise HandoffBlocked("event_missing")
    current = Handoff(key, Phase(record["phase"]), record["revision"])
    updated = transition(current, Phase(target), expected_revision=expected_revision)
    copy = dict(events)
    copy[key] = {"phase": updated.phase.value, "revision": updated.revision}
    _persist(copy, sha)
    return updated


def quarantine_inflight_after_crash(message_key):
    key = _fingerprint(message_key)
    sha, events = _load()
    record = events.get(key)
    if record is None:
        raise HandoffBlocked("event_missing")
    current = Handoff(key, Phase(record["phase"]), record["revision"])
    recovered = recover_after_crash(current)
    if recovered == current:
        return recovered
    copy = dict(events)
    copy[key] = {"phase": recovered.phase.value, "revision": recovered.revision}
    _persist(copy, sha)
    return recovered
