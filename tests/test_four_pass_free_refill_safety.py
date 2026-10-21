"""Four-pass OFFLINE safety acceptance for ALDI free 1-GB refill.

No WebDriver, network, credentials or provider click is used here. One simulated
candidate is never a license to submit two operations: the durable handoff
contract prevents duplicate reservation and quarantines in-flight uncertainty.
"""
import pytest

from core.aldi_refill import assess_refill
from core.mail_actor_handoff import (
    HandoffBlocked, Phase, recover_after_crash, reserve, transition,
)


def offer(**changes):
    fields = dict(
        page_text="ALDI TALK Tarif S Unlimited",
        active_tariff_text="Tarif S Unlimited",
        offer_text="1 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 €",
        button_text="1 GB nachbuchen",
        enabled=True,
        candidate_count=1,
        remaining_gb=0.4,
    )
    fields.update(changes)
    return assess_refill(**fields)


def test_round_1_verified_zero_euro_candidate_and_second_click_blocked():
    """One valid simulated selection; a second click is NOT permitted."""
    decision = offer()
    assert decision["refill_eligible"] is True
    assert decision["free_evidence"] == "explicit_free_offer"
    original = reserve(None, "a" * 64, "consumed")
    with pytest.raises(HandoffBlocked, match="duplicate_or_unresolved_event"):
        reserve(original, "a" * 64, "consumed")
    flight = transition(original, Phase.IN_FLIGHT, expected_revision=0)
    unknown = recover_after_crash(flight)
    assert unknown.phase == Phase.QUARANTINED_UNKNOWN
    with pytest.raises(HandoffBlocked, match="unsafe_transition"):
        transition(unknown, Phase.IN_FLIGHT, expected_revision=unknown.revision)


def test_round_2_paid_and_tariff_change_are_never_candidates():
    assert offer(offer_text="1 GB Datenvolumen nachbuchen 0,99 €")["refill_eligible"] is False
    assert offer(offer_text="1 GB Datenvolumen nachbuchen 0,00 € Tarif wechseln")["refill_eligible"] is False
    assert offer(active_tariff_text="Jahres-Paket S")["refill_eligible"] is False


@pytest.mark.parametrize("count", [0, 2, True, 1.0, None])
def test_round_3_ambiguous_or_noninteger_candidate_is_blocked(count):
    result = offer(candidate_count=count)
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "refill_control_ambiguous"


def test_round_4_early_warning_and_repeat_after_unknown_blocked():
    with pytest.raises(HandoffBlocked, match="not_consumed"):
        reserve(None, "b" * 64, "80_percent")
    first = reserve(None, "b" * 64, "consumed")
    inflight = transition(first, Phase.IN_FLIGHT, expected_revision=0)
    unknown = recover_after_crash(inflight)
    assert unknown.phase == Phase.QUARANTINED_UNKNOWN
    with pytest.raises(HandoffBlocked, match="duplicate_or_unresolved_event"):
        reserve(unknown, "b" * 64, "consumed")
    with pytest.raises(HandoffBlocked, match="provider_receipt_verifier_unavailable"):
        transition(inflight, Phase.COMPLETED, expected_revision=1)
