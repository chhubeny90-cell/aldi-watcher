"""Read-only LIDL readiness summary. No login, request or booking is performed."""

from collections.abc import Mapping

STAGES = (
    "portal_access",
    "authenticated_account",
    "active_tariff",
    "exact_free_offer",
    "operation_journal",
    "provider_receipt",
)

def readiness(evidence):
    """Return safe next action and blocker names, never infer success from missing data.

    Each field must be precisely True, False, or None. Other values fail closed.
    """
    if not isinstance(evidence, Mapping):
        return {"status": "BLOCKED", "blockers": list(STAGES), "next_step": "public_diagnostic"}
    blockers = [key for key in STAGES if evidence.get(key) is not True]
    if not blockers:
        # Reporting all indicators true is not a release authorization.
        return {"status": "REVIEW_REQUIRED", "blockers": [], "next_step": "independent_verification"}
    if "portal_access" in blockers:
        step = "public_diagnostic"
    elif "authenticated_account" in blockers:
        step = "manual_read_only_login"
    elif "active_tariff" in blockers or "exact_free_offer" in blockers:
        step = "read_only_offer_inspection"
    else:
        step = "journal_and_receipt_review"
    return {"status": "BLOCKED", "blockers": blockers, "next_step": step}
