from core.aldi_refill import assess_refill


def eligible(**overrides):
    args = dict(
        page_text='ALDI TALK Tarif S Unlimited',
        offer_text='1 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 €',
        button_text='1 GB nachbuchen',
        enabled=True,
        candidate_count=1,
        remaining_gb=0.42,
    )
    args.update(overrides)
    return assess_refill(**args)


def test_free_tarif_s_one_gb_is_eligible():
    result = eligible()
    assert result['refill_eligible'] is True
    assert result['refill_type'] == 'FREE_UNLIMITED'
    assert result['refill_reason'] == 'free_one_gb_button_available'
    assert result['tariff_evidence'] == 'UNLIMITED'


def test_tarif_m_is_supported():
    result = eligible(page_text='ALDI TALK Tarif M Unlimited')
    assert result['refill_eligible'] is True
    assert result['tariff_evidence'] == 'UNLIMITED'


def test_tarif_l_is_supported():
    result = eligible(page_text='ALDI TALK Tarif L Unlimited')
    assert result['refill_eligible'] is True
    assert result['tariff_evidence'] == 'UNLIMITED'


def test_exactly_one_gb_is_still_eligible():
    result = eligible(remaining_gb=1.0)
    assert result['refill_eligible'] is True


def test_volume_above_one_gb_is_rejected():
    result = eligible(remaining_gb=1.001)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'remaining_volume_above_one_gb'


def test_legacy_unlimited_marker_remains_supported():
    result = eligible(page_text='ALDI TALK Unlimited')
    assert result['refill_eligible'] is True
    assert result['tariff_evidence'] == 'UNLIMITED'


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


def test_ordinary_tarif_names_do_not_authorize_refill():
    for size in ('S', 'M', 'L'):
        result = eligible(page_text=f'ALDI TALK Tarif {size}')
        assert result['refill_eligible'] is False
        assert result['refill_reason'] == 'active_tariff_unverified'


def test_annual_tariff_and_generic_unlimited_hint_are_rejected():
    for tariff in ('Jahres-Paket XS', 'Jahrespaket S', 'Jahrestarif',
                   'Jahres Tarif', 'Basis-Tarif'):
        result = eligible(page_text=f'{tariff}\nALDI TALK Unlimited')
        assert result['refill_eligible'] is False


def test_unlimited_in_marketing_text_is_not_a_tariff_identity():
    result = eligible(page_text='Mit Unlimited kannst du kostenlos 1 GB nachbuchen')
    assert result['refill_eligible'] is False


def test_minutes_and_sms_unlimited_do_not_authorize_data_refill():
    result = eligible(page_text='Unbegrenzt Min.\nUnbegrenzt SMS')
    assert result['refill_eligible'] is False


def test_live_tariff_heading_overrides_generic_body_hint():
    result = eligible(page_text='ALDI TALK Unlimited',
                      active_tariff_text='Jahres-Paket S')
    assert result['refill_eligible'] is False


def test_missing_live_tariff_heading_fails_closed():
    result = eligible(page_text='ALDI TALK Unlimited', active_tariff_text='')
    assert result['refill_eligible'] is False


def test_explicit_unlimited_heading_with_verified_free_offer_is_eligible():
    result = eligible(page_text='Übersicht Guthaben Datenvolumen',
                      active_tariff_text='Tarif M Unlimited')
    assert result['refill_eligible'] is True


def test_multiple_unlimited_tariff_headings_are_ambiguous():
    result = eligible(active_tariff_text='Tarif S Unlimited\nTarif M Unlimited')
    assert result['refill_eligible'] is False
\n\ndef test_refill_heading_is_not_active_tariff_evidence():\n    result = eligible(active_tariff_text="Tarif S\\nUnlimited GB nachbuchen")\n    assert result["refill_eligible"] is False\n    assert result["refill_reason"] == "active_tariff_unverified"\n\n\ndef test_refill_heading_alone_is_not_active_tariff_evidence():\n    result = eligible(active_tariff_text="Unlimited GB nachbuchen")\n    assert result["refill_eligible"] is False\n    assert result["refill_reason"] == "active_tariff_unverified"\n