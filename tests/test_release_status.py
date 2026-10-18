from core.release_status import evaluate, audit


def test_missing_evidence_is_blocked():
    assert evaluate({})["status"] == "BLOCKED"


def test_active_blocker_prevents_live():
    d = ready()
    d["blockers"] = [{"id": "BLOCK-001", "active": True}]
    assert evaluate(d)["status"] == "BLOCKED"


def ready():
    return {
        "changes": [{"id": "CHG-1", "status": "BEWERTET", "category": "DOCS"}],
        "evidence": [{"valid": True, "url": "https://example.invalid/evidence",
                      "artifact": "artifact", "log": "log", "commit": "abc"}],
        "tests": [{"status": "BESTANDEN", "reproducible": True}],
        "blockers": [], "dry": {f"DRY-{i:03d}": True for i in range(1, 10)},
        "live": {}, "pending": 0, "unknown": 0, "unresolved": False,
        "external_actions_possible": False,
    }


def test_dry_ready_only_with_all_proofs():
    assert evaluate(ready())["status"] == "DRY_RUN_READY"


def test_unreviewed_commit_downgrades():
    d = ready()
    d["changes"][0]["status"] = "OFFEN"
    assert evaluate(d)["status"] == "BLOCKED"


def test_security_change_invalidates_evidence():
    d = ready()
    d["changes"][0]["category"] = "BOOKING"
    d["evidence"][0]["change_id"] = "CHG-1"
    assert evaluate(d)["status"] == "BLOCKED"


def test_unknown_never_live_ready():
    d = ready()
    d["unknown"] = 1
    assert evaluate(d)["status"] == "BLOCKED"


def test_live_requires_explicit_proofs():
    d = ready()
    d["live"] = {"LIVE-001": True}
    d["live_authorization"] = True
    d["provider_receipt_verified"] = True
    d["account_binding_verified"] = True
    assert evaluate(d)["status"] == "LIVE_READY"


def test_audit_only_on_transition():
    assert audit("BLOCKED", {"status": "BLOCKED", "reasons": []},
                 commit="abc", change_id="chg", responsible="maintainer") is None
    entry = audit("DRY_RUN_READY", {"status": "BLOCKED", "reasons": ["STATUS-RULE-004"]},
                  commit="abc", change_id="chg", responsible="maintainer",
                  timestamp="2026-10-18T15:16:00+02:00")
    assert entry["new_status"] == "BLOCKED" and len(entry["sha256"]) == 64
