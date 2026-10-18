"""Deterministic, fail-closed release readiness evaluator. No provider actions."""
from datetime import datetime, timezone
import hashlib
import json

STATUSES = ("BLOCKED", "DRY_RUN_READY", "LIVE_READY")
SECURITY = {"SECURITY", "AUTH", "SECRETS", "BOOKING", "JOURNAL", "CAS"}


def evaluate(data):
    """Pure calculation; missing or malformed evidence always blocks."""
    reasons = []
    if not isinstance(data, dict):
        data = {}
        reasons.append("INVALID_INPUT")
    changes = data.get("changes", [])
    evidence = data.get("evidence", [])
    tests = data.get("tests", [])
    blockers = data.get("blockers", [])
    dry = data.get("dry", {})
    live = data.get("live", {})
    if not all(isinstance(x, list) for x in (changes, evidence, tests, blockers)):
        return {"status": "BLOCKED", "reasons": ["INVALID_INPUT"]}
    if any(not isinstance(x, dict) for x in changes + evidence + tests + blockers):
        return {"status": "BLOCKED", "reasons": ["INVALID_INPUT"]}
    if not isinstance(dry, dict) or not isinstance(live, dict):
        return {"status": "BLOCKED", "reasons": ["INVALID_INPUT"]}
    if any(b.get("active") is not False for b in blockers):
        reasons.append("STATUS-RULE-004")
    if any(c.get("status") != "BEWERTET" for c in changes):
        reasons.append("STATUS-RULE-002")
    changed = {c.get("id") for c in changes if c.get("category") in SECURITY}
    if any(e.get("change_id") in changed and not e.get("revalidated") for e in evidence):
        reasons.append("STATUS-RULE-003")
    if not evidence or any(
        e.get("valid") is not True or not all(e.get(k) for k in ("url", "artifact", "log", "commit"))
        for e in evidence
    ):
        reasons.append("STATUS-RULE-007")
    if not tests or any(t.get("status") != "BESTANDEN" or not t.get("reproducible") for t in tests):
        reasons.append("STATUS-RULE-005/006")
    if data.get("pending", 1) != 0 or data.get("unknown", 1) != 0:
        reasons.append("STATUS-RULE-013")
    if data.get("unresolved", True) is not False:
        reasons.append("UNKNOWN_STATE")
    if any(dry.get(f"DRY-{i:03d}") is not True for i in range(1, 10)):
        reasons.append("STATUS-RULE-008")
    if data.get("external_actions_possible") is not False:
        reasons.append("EXTERNAL_ACTIONS_NOT_DISABLED")
    if reasons:
        return {"status": "BLOCKED", "reasons": sorted(set(reasons))}
    if (live and all(v is True for v in live.values()) and
        data.get("live_authorization") is True and
        data.get("provider_receipt_verified") is True and
        data.get("account_binding_verified") is True):
        return {"status": "LIVE_READY", "reasons": []}
    return {"status": "DRY_RUN_READY", "reasons": []}


def audit(previous, current, *, commit, change_id, responsible, timestamp=None):
    if previous not in STATUSES or current["status"] not in STATUSES:
        raise ValueError("invalid status")
    if previous == current["status"]:
        return None
    record = {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "old_status": previous, "new_status": current["status"],
        "trigger": current["reasons"][0] if current["reasons"] else "CRITERIA_MET",
        "commit": commit, "change_id": change_id, "responsible": responsible,
    }
    if not all(record.values()):
        raise ValueError("incomplete audit")
    record["sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    return record
