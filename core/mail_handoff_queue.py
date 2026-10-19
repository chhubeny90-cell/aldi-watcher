"""CAS-backed mail event queue. Never dispatches or invokes the provider.

Persist only keyed HMAC fingerprints; a crash after reserving an event is
recoverable without claiming it processed. Unknown in-flight work is quarantined.
"""
from datetime import datetime, timedelta, timezone

from core.mail_actor_handoff import Handoff, HandoffBlocked, Phase, recover_after_crash, reserve, transition
from github_hardening_state import _aux_path, _mac, _read_json, _write_json, _trigger_state

QUEUE_VERSION = 1
MAX_EVENTS = 512


def _load(ref=None):
    current = (_read_json(_aux_path("mail-handoff"), ref=ref) if ref is not None
               else _read_json(_aux_path("mail-handoff")))
    if current is None:
        return None, {}
    sha, data = current
    events = data.get("events")
    if data.get("version") != QUEUE_VERSION or not isinstance(events, dict) or len(events) > MAX_EVENTS:
        raise HandoffBlocked("queue_invalid")
    for key, record in events.items():
        if (not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key) or
                not isinstance(record, dict) or set(record) not in (
                    {"phase", "revision"}, {"phase", "revision", "completed_at"}) or
                type(record["phase"]) is not str or record["phase"] not in Phase._value2member_map_ or
                type(record["revision"]) is not int or record["revision"] < 0):
            raise HandoffBlocked("queue_invalid")
        if "completed_at" in record:
            if record["phase"] != Phase.COMPLETED.value:
                raise HandoffBlocked("queue_invalid")
            _completion_time(record["completed_at"])
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


def _legacy_seen(message_key, legacy_message_key=None):
    # Read errors propagate: unavailable history is never treated as empty.
    _, state = _trigger_state()
    # Copy all still-retained legacy trigger keys into an unbounded migration
    # ledger. Do this before reserving, never after acknowledging the mail.
    path = _aux_path("legacy-trigger-history")
    current = _read_json(path)
    sha, history = current if current is not None else (None, {"version": 1, "keys": []})
    keys = history.get("keys")
    if (history.get("version") != 1 or not isinstance(keys, list)
            or any(not isinstance(key, str) or len(key) != 64
                   or any(c not in "0123456789abcdef" for c in key) for key in keys)):
        raise HandoffBlocked("legacy_history_invalid")
    merged = sorted(set(keys).union(state["keys"]))
    if merged != sorted(set(keys)):
        _write_json(path, {"version": 1, "keys": merged}, sha,
                    message="Preserve legacy ALDI trigger deduplication")
    return any(_mac("trigger", key) in merged
               for key in (message_key, legacy_message_key) if key is not None)


def _completion_time(value):
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise HandoffBlocked("completion_time_invalid") from None


def _archive():
    current = _read_json(_aux_path("provider-journal"))
    if current is None:
        return None, {}
    sha, data = current
    tombstones = data.get("tombstones")
    if data.get("version") != 1 or not isinstance(tombstones, dict):
        raise HandoffBlocked("archive_invalid")
    for key, record in tombstones.items():
        if (not isinstance(key, str) or len(key) != 64
                or any(c not in "0123456789abcdef" for c in key)
                or not isinstance(record, dict)
                or set(record) != {"phase", "revision", "completed_at"}
                or record["phase"] != Phase.COMPLETED.value
                or type(record["revision"]) is not int or record["revision"] < 0):
            raise HandoffBlocked("archive_invalid")
        _completion_time(record["completed_at"])
    return sha, tombstones


def archive_completed(now=None):
    """Archive first, then CAS-remove; a crash can duplicate but never lose a guard.

    No code here creates completion evidence. Legacy COMPLETED records without
    an aware timestamp remain in the queue until verified independently.
    """
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise HandoffBlocked("naive_archive_reference")
    sha, events = _load()
    retired = {key: record for key, record in events.items()
               if record["phase"] == Phase.COMPLETED.value and "completed_at" in record
               and reference - _completion_time(record["completed_at"]) > timedelta(days=30)}
    if not retired:
        return 0
    archive_sha, tombstones = _archive()
    for key, record in retired.items():
        if key in tombstones and tombstones[key] != record:
            raise HandoffBlocked("archive_conflict")
    _write_json(_aux_path("provider-journal"),
                {"version": 1, "tombstones": {**tombstones, **retired}}, archive_sha,
                message="Retain completed ALDI mail tombstones")
    _persist({key: record for key, record in events.items() if key not in retired}, sha)
    return len(retired)


def enqueue_consumed(message_key, signal, *, legacy_message_key=None):
    """Return True only after the remote reservation has been committed."""
    if signal != "consumed":
        raise HandoffBlocked("not_consumed")
    key = _fingerprint(message_key)
    for attempt in range(2):
        sha, events = _load()
        _, tombstones = _archive()
        if _legacy_seen(message_key, legacy_message_key):
            return False
        # Old queue keys were derived from the original SHA-256 mail identity.
        aliases = {key}
        if legacy_message_key is not None:
            aliases.add(_fingerprint(legacy_message_key))
        if aliases.intersection(events) or aliases.intersection(tombstones):
            return False
        if len(events) >= MAX_EVENTS:
            archive_completed()
            sha, events = _load()
            if key in events:
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
