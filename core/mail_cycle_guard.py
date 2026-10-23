"""Durable, fail-closed *candidate* guard for repeated consumed-volume mail.

This guard has no provider adapter and grants NO booking permission. A configured
profile is not proof of SIM identity. It deliberately has no timer-based release,
and a different Message-ID cannot open another candidate for the same profile.
Only a future authenticated provider-cycle verifier may define a new cycle.
"""
from core.mail_actor_handoff import HandoffBlocked
from github_hardening_state import _aux_path, _mac, _read_json, _write_json

VERSION = 1
MAX_PROFILES = 128
_VALID_STATES = {"UNVERIFIED", "UNKNOWN"}


def _identity(value, label):
    if (not isinstance(value, str) or not value.strip()
            or len(value) > 512 or value != value.strip()):
        raise HandoffBlocked("invalid_" + label)
    return _mac("mail-cycle-" + label, value)


def _load():
    current = _read_json(_aux_path("mail-cycle-guard"))
    if current is None:
        return None, {}
    sha, payload = current
    profiles = payload.get("profiles")
    if (payload.get("version") != VERSION or not isinstance(profiles, dict)
            or len(profiles) > MAX_PROFILES):
        raise HandoffBlocked("cycle_guard_invalid")
    for key, record in profiles.items():
        if (not _digest(key) or not isinstance(record, dict)
                or set(record) != {"state", "first_message"}
                or record["state"] not in _VALID_STATES
                or not _digest(record["first_message"])):
            raise HandoffBlocked("cycle_guard_invalid")
    return sha, profiles


def _digest(value):
    return (isinstance(value, str) and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value))


def _persist(profiles, sha):
    if len(profiles) > MAX_PROFILES:
        raise HandoffBlocked("cycle_guard_capacity_reached")
    _write_json(_aux_path("mail-cycle-guard"),
                {"version": VERSION, "profiles": profiles}, sha,
                message="Reserve unresolved ALDI consumption candidate")


def reserve_unverified_candidate(profile_binding, message_key):
    """Return True only for the first CAS-persisted candidate for a profile.

    Caller must obtain profile_binding from an explicit configuration. It is
    NOT an authenticated provider account binding. Never interpret True as
    authority to book; it only authorizes reporting a pending candidate.
    """
    profile = _identity(profile_binding, "profile")
    message = _identity(message_key, "message")
    for attempt in range(3):
        sha, profiles = _load()
        if profile in profiles:
            return False
        if len(profiles) >= MAX_PROFILES:
            raise HandoffBlocked("cycle_guard_capacity_reached")
        updated = dict(profiles)
        updated[profile] = {"state": "UNVERIFIED", "first_message": message}
        try:
            _persist(updated, sha)
            return True
        except RuntimeError as exc:
            if str(exc) != "github_aux_state_conflict" or attempt == 2:
                raise
    raise HandoffBlocked("cycle_guard_unconfirmed")


def quarantine_unknown(profile_binding):
    """Irreversibly block further candidates after an uncertain operation."""
    profile = _identity(profile_binding, "profile")
    for attempt in range(3):
        sha, profiles = _load()
        current = profiles.get(profile)
        if current is None:
            raise HandoffBlocked("cycle_candidate_missing")
        if current["state"] == "UNKNOWN":
            return False
        updated = dict(profiles)
        updated[profile] = {**current, "state": "UNKNOWN"}
        try:
            _persist(updated, sha)
            return True
        except RuntimeError as exc:
            if str(exc) != "github_aux_state_conflict" or attempt == 2:
                raise
    raise HandoffBlocked("cycle_guard_unconfirmed")


def reserve_verified_provider_cycle(*_args, **_kwargs):
    """No authenticated provider cycle verifier exists. Fail closed."""
    raise HandoffBlocked("provider_cycle_verifier_unavailable")
