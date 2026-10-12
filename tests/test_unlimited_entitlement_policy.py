from core.aldi_refill import assess_refill


def _assess(**overrides):
    args = dict(
        page_text='ALDI TALK Tarif M Unlimited',
        offer_text='1 GB Highspeed-Datenvolumen nachbuchen',
        button_text='+1 GB',
        enabled=True,
        candidate_count=1,
        remaining_gb=0.42,
    )
    args.update(overrides)
    return assess_refill(**args)


def test_verified_unlimited_allows_exact_one_gb_without_local_price_label():
    result = _assess()
    assert result['refill_eligible'] is True
    assert result['refill_type'] == 'FREE_UNLIMITED'
    assert result['free_evidence'] == 'official_unlimited_entitlement'


def test_positive_price_still_blocks_unlimited_refill():
    result = _assess(offer_text='1 GB Highspeed-Datenvolumen nachbuchen 0,99 €')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'


def test_tarif_s_without_explicit_zero_price_stays_blocked():
    result = _assess(
        page_text='Tarif S',
        active_tariff_text='Tarif S',
        offer_text='1 GB Highspeed-Datenvolumen nachbuchen',
    )
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'


def test_exact_one_gb_and_unique_control_are_still_required():
    assert _assess(offer_text='2 GB Highspeed-Datenvolumen nachbuchen')['refill_eligible'] is False
    assert _assess(candidate_count=2)['refill_eligible'] is False


def test_refill_requires_remaining_volume_below_one_gb():
    result = _assess(remaining_gb=1.0)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'remaining_volume_above_one_gb'
