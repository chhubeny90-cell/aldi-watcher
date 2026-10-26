"""Auxiliary public-safe state for hosted ALDI hardening.

This module stores only non-identifying HMAC proofs, trigger fingerprints and
heartbeat timestamps on the dedicated state branch. It never stores phone
numbers, passwords, allowance values, tariff text or provider error text.
"""

import base64
import hashlib
import hmac
import json
import math
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from github_journal_state import _branch, _ensure_branch, _headers, _url, _get_state, _put_state


MAX_TRIGGER_KEYS = 128
RECOVERY_VERSION = 1
TRIGGER_VERSION = 1
HEARTBEAT_VERSION = 1


def _aux_path(kind):
    configured = os.environ.get("ALDI_STATE_PATH", ".aldi-state/profile-1.json").strip()
    if not configured:
        configured = ".aldi-state/profile-1.json"
    if configured.endswith(".json"):
        configured = configured[:-5]
    return f"{configured}.{kind}.json"


def _secret_key():
    value = (os.environ.get("ALDI_RECOVERY_KEY")
             or os.environ.get("ALDI_PASS_ENC")
             or os.environ.get("ALDI_PASS"))
    if not value:
        raise RuntimeError("recovery_key_unavailable")
    return value.encode("utf-8")


def _mac(label, *parts):
    payload = "|".join([label, *[str(part) for part in parts]]).encode("utf-8")
    return hmac.new(_secret_key(), payload, hashlib.sha256).hexdigest()


def _read_json(path, ref=None):
    if ref is None:
        _ensure_branch()
    encoded_branch = quote(ref if ref is not None else _branch(), safe="")
    encoded_path = quote(path, safe="/")
    response = requests.get(
        _url(f"contents/{encoded_path}?ref={encoded_branch}"),
        headers=_headers(), timeout=20,
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RuntimeError(f"github_aux_read_http_{response.status_code}")
    payload = response.json()
    if payload.get("type") != "file" or not payload.get("sha"):
        raise RuntimeError("github_aux_metadata_invalid")
    try:
        content = base64.b64decode(payload.get("content", ""), validate=False)
        decoded = json.loads(content.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("github_aux_content_invalid") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("github_aux_content_invalid")
    return payload["sha"], decoded


def _write_json(path, payload, current_sha=None, message="Persist ALDI hardening state"):
    # These commits update data on the state branch, never application code.
    # Mail cursors and fingerprints must not fan out into full CI matrices.
    if "[skip ci]" not in message:
        message += " [skip ci]"
    body = {
        "message": message,
        "content": base64.b64encode(
            (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        ).decode("ascii"),
        "branch": _branch(),
    }
    if current_sha is not None:
        body["sha"] = current_sha
    encoded_path = quote(path, safe="/")
    response = requests.put(
        _url(f"contents/{encoded_path}"), headers=_headers(), json=body, timeout=20,
    )
    if response.status_code not in {200, 201}:
        if response.status_code in {409, 422}:
            raise RuntimeError("github_aux_state_conflict")
        raise RuntimeError(f"github_aux_write_http_{response.status_code}")


def _validate_recharge_id(recharge_id):
    try:
        parsed = uuid.UUID(str(recharge_id))
    except (ValueError, AttributeError):
        raise RuntimeError("invalid_recharge_id") from None
    if str(parsed) != str(recharge_id):
        raise RuntimeError("invalid_recharge_id")
    return str(parsed)


def _empty_recovery():
    return {"version": RECOVERY_VERSION, "operations": {}}


def _recovery_state():
    current = _read_json(_aux_path("recovery"))
    if current is None:
        return None, _empty_recovery()
    sha, payload = current
    if payload.get("version") != RECOVERY_VERSION or not isinstance(payload.get("operations"), dict):
        raise RuntimeError("recovery_state_invalid")
    for recharge_id, proof in payload["operations"].items():
        _validate_recharge_id(recharge_id)
        if (not isinstance(proof, dict)
                or set(proof) != {"before_mib_mac", "binding_mac"}
                or not all(isinstance(proof.get(key), str) and len(proof[key]) == 64
                           for key in ("before_mib_mac", "binding_mac"))):
            raise RuntimeError("recovery_state_invalid")
    return sha, payload


def set_recovery_proof(recharge_id, before_gb, binding):
    recharge_id = _validate_recharge_id(recharge_id)
    if (isinstance(before_gb, bool) or not isinstance(before_gb, (int, float))
            or not math.isfinite(before_gb) or not 0 <= before_gb < 1.0):
        raise RuntimeError("recovery_baseline_invalid")
    if (not isinstance(binding, tuple) or len(binding) != 2
            or not all(isinstance(item, str) and item for item in binding)):
        raise RuntimeError("recovery_binding_invalid")
    before_mib = int(round(float(before_gb) * 1024.0))
    before_mib = max(0, min(1024, before_mib))
    sha, state = _recovery_state()
    state["operations"][recharge_id] = {
        "before_mib_mac": _mac("before", recharge_id, before_mib),
        "binding_mac": _mac("binding", recharge_id, binding[0], binding[1]),
    }
    _write_json(
        _aux_path("recovery"), state, sha,
        message="Persist ALDI recovery proof before provider click",
    )


def get_recovery_proof(recharge_id):
    recharge_id = _validate_recharge_id(recharge_id)
    _, state = _recovery_state()
    proof = state["operations"].get(recharge_id)
    return dict(proof) if proof is not None else None


def clear_recovery_proof(recharge_id):
    recharge_id = _validate_recharge_id(recharge_id)
    sha, state = _recovery_state()
    if recharge_id not in state["operations"]:
        return False
    del state["operations"][recharge_id]
    _write_json(_aux_path("recovery"), state, sha, message="Clear terminal ALDI recovery proof")
    return True


def recover_before_gb(recharge_id, proof):
    recharge_id = _validate_recharge_id(recharge_id)
    if not isinstance(proof, dict) or not isinstance(proof.get("before_mib_mac"), str):
        return None
    expected = proof["before_mib_mac"]
    for before_mib in range(0, 1025):
        candidate = _mac("before", recharge_id, before_mib)
        if hmac.compare_digest(candidate, expected):
            return before_mib / 1024.0
    return None


def recovery_binding_matches(recharge_id, proof, binding):
    recharge_id = _validate_recharge_id(recharge_id)
    if (not isinstance(proof, dict) or not isinstance(proof.get("binding_mac"), str)
            or not isinstance(binding, tuple) or len(binding) != 2):
        return False
    actual = _mac("binding", recharge_id, binding[0], binding[1])
    return hmac.compare_digest(actual, proof["binding_mac"])


def _trigger_state():
    current = _read_json(_aux_path("triggers"))
    if current is None:
        return None, {"version": TRIGGER_VERSION, "keys": []}
    sha, payload = current
    keys = payload.get("keys")
    if (payload.get("version") != TRIGGER_VERSION or not isinstance(keys, list)
            or len(keys) > MAX_TRIGGER_KEYS
            or not all(isinstance(item, str) and len(item) == 64 for item in keys)):
        raise RuntimeError("trigger_state_invalid")
    return sha, payload


def claim_trigger_key(message_key):
    """Return True only once for a non-secret mail/event key.

    The state branch receives only a keyed HMAC, never the original Message-ID.
    A GitHub SHA conflict is retried once so simultaneous duplicate events cannot
    both proceed.
    """
    if not isinstance(message_key, str) or not message_key.strip() or len(message_key) > 512:
        raise RuntimeError("trigger_key_invalid")
    fingerprint = _mac("trigger", message_key.strip())
    for attempt in range(2):
        sha, state = _trigger_state()
        if fingerprint in state["keys"]:
            return False
        state["keys"] = (state["keys"] + [fingerprint])[-MAX_TRIGGER_KEYS:]
        try:
            _write_json(_aux_path("triggers"), state, sha, message="Claim ALDI usage-mail trigger")
            return True
        except RuntimeError as exc:
            if str(exc) != "github_aux_state_conflict" or attempt:
                raise
    return False


def touch_heartbeat(now=None):
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise RuntimeError("naive_heartbeat_reference")
    timestamp = reference.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    path = _aux_path("heartbeat")
    for attempt in range(2):
        current = _read_json(path)
        sha = None if current is None else current[0]
        payload = {"version": HEARTBEAT_VERSION, "last_run_at": timestamp}
        try:
            _write_json(path, payload, sha, message="Update ALDI watcher heartbeat")
            return timestamp
        except RuntimeError as exc:
            if str(exc) != "github_aux_state_conflict" or attempt:
                raise
    return timestamp


def heartbeat_age_seconds(now=None):
    current = _read_json(_aux_path("heartbeat"))
    if current is None:
        return None
    payload = current[1]
    if payload.get("version") != HEARTBEAT_VERSION or not isinstance(payload.get("last_run_at"), str):
        raise RuntimeError("heartbeat_state_invalid")
    try:
        last = datetime.fromisoformat(payload["last_run_at"].replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeError("heartbeat_state_invalid") from None
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise RuntimeError("naive_heartbeat_reference")
    return max(0.0, (reference.astimezone(timezone.utc) - last.astimezone(timezone.utc)).total_seconds())


def clear_auth_backoff():
    """Clear a stale auth retry time after an explicitly proven successful login."""
    current = _get_state()
    if current is None:
        return False
    sha, state = current
    if state.get("auth_retry_after") is None:
        return False
    state = dict(state)
    state["auth_retry_after"] = None
    _put_state(state, sha, message="Clear ALDI authentication backoff after successful login")
    return True
