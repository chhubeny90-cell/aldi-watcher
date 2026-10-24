"""Offline regression tests for the no-action LIDL readiness summary."""
import pytest
from core.lidl_readiness import STAGES, readiness

def test_unknown_status_fails_closed():
    result = readiness({})
    assert result["status"] == "BLOCKED"
    assert result["blockers"] == list(STAGES)
    assert result["next_step"] == "public_diagnostic"

@pytest.mark.parametrize("value", [False, None, 1, "true", "", [], {}])
def test_non_boolean_portal_never_passes(value):
    data = {key: True for key in STAGES}
    data["portal_access"] = value
    assert readiness(data)["status"] == "BLOCKED"

def test_403_routes_to_public_diagnostic():
    data = {key: True for key in STAGES}
    data["portal_access"] = False
    assert readiness(data)["next_step"] == "public_diagnostic"

def test_login_missing_routes_read_only():
    data = {key: True for key in STAGES}
    data["authenticated_account"] = None
    assert readiness(data)["next_step"] == "manual_read_only_login"

def test_tariff_and_offer_require_proof():
    data = {key: True for key in STAGES}
    data["exact_free_offer"] = False
    assert readiness(data)["next_step"] == "read_only_offer_inspection"

def test_journal_missing_remains_blocked():
    data = {key: True for key in STAGES}
    data["operation_journal"] = False
    assert readiness(data)["next_step"] == "journal_and_receipt_review"

def test_all_claims_still_need_independent_review():
    result = readiness({key: True for key in STAGES})
    assert result == {"status": "REVIEW_REQUIRED", "blockers": [], "next_step": "independent_verification"}

def test_input_invalid_type_stays_blocked():
    assert readiness(None)["status"] == "BLOCKED"

@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("value", [False, None, 0, 1, "true", "", [], {}])
def test_each_stage_requires_literal_true(stage, value):
    data = dict.fromkeys(STAGES, True)
    data[stage] = value
    result = readiness(data)
    assert result["status"] == "BLOCKED"
    assert result["blockers"] == [stage]


@pytest.mark.parametrize(
    ("stage", "expected_step"),
    [
        ("portal_access", "public_diagnostic"),
        ("authenticated_account", "manual_read_only_login"),
        ("active_tariff", "read_only_offer_inspection"),
        ("exact_free_offer", "read_only_offer_inspection"),
        ("operation_journal", "journal_and_receipt_review"),
        ("provider_receipt", "journal_and_receipt_review"),
    ],
)
def test_first_missing_stage_controls_next_step(stage, expected_step):
    data = dict.fromkeys(STAGES, True)
    missing = STAGES[STAGES.index(stage):]
    for key in missing:
        del data[key]
    result = readiness(data)
    assert result == {
        "status": "BLOCKED",
        "blockers": list(missing),
        "next_step": expected_step,
    }


def test_evidence_is_not_mutated_and_results_do_not_leak_state():
    data = dict.fromkeys(STAGES, True)
    data["provider_receipt"] = None
    original = data.copy()
    first = readiness(data)
    first["blockers"].clear()
    assert data == original
    assert readiness(data)["blockers"] == ["provider_receipt"]
