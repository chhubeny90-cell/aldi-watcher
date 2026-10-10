from core.aldi_refill import assess_refill


def eligible(**overrides):
    args = dict(
        page_text='ALDI TALK Unlimited Tarif Datenvolumen',
        offer_text='1 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 €',
        button_text='1 GB nachbuchen',
        enabled=True,
        candidate_count=1,
        remaining_gb=0.42,
    )
    args.update(overrides)
    return assess_refill(**args)


def test_free_unlimited_one_gb_is_eligible():
    result = eligible()
    assert result['refill_eligible'] is True
    assert result['refill_type'] == 'FREE_UNLIMITED'
    assert result['refill_reason'] == 'free_one_gb_button_available'


def test_remaining_volume_must_be_below_one_gb():
    result = eligible(remaining_gb=1.0)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'remaining_volume_not_below_one_gb'


def test_paid_offer_is_rejected():
    result = eligible(offer_text='1 GB Highspeed-Datenvolumen für 2,99 € nachbuchen')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'


def test_missing_free_evidence_is_rejected():
    result = eligible(offer_text='1 GB Highspeed-Datenvolumen nachbuchen')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'


def test_multiple_candidate_controls_are_rejected():
    result = eligible(candidate_count=2)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'refill_control_ambiguous'
    assert result['refill_candidate_count'] == 2


def test_wrong_tariff_is_rejected():
    result = eligible(page_text='ALDI TALK Jahrespaket Datenvolumen')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'active_tariff_unverified'


def test_non_one_gb_offer_is_rejected():
    result = eligible(offer_text='2 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 €')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'not_exactly_one_gb'


def test_disabled_button_is_rejected():
    result = eligible(enabled=False)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'button_disabled'


def test_conflicting_terms_are_rejected_even_with_zero_price():
    result = eligible(offer_text='1 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 € monatlich')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'conflicting_terms'
