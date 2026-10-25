from core.aldi_refill import assess_refill


def assess(*, tariff="Tarif S Unlimited", offer="Unlimited 1 GB nachbuchen", remaining=0.25):
    return assess_refill(
        page_text="Kundenübersicht",
        active_tariff_text=tariff,
        offer_text=offer,
        button_text="+1 GB",
        enabled=True,
        candidate_count=1,
        remaining_gb=remaining,
    )


def test_unlimited_on_demand_without_price_is_blocked():
    result = assess()
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "price_unverified_or_paid"


def test_generic_one_gb_without_price_is_blocked():
    result = assess(offer="1 GB Highspeed-Datenvolumen nachbuchen")
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "price_unverified_or_paid"


def test_free_word_without_price_is_blocked():
    result = assess(offer="1 GB Highspeed-Datenvolumen kostenlos nachbuchen")
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "price_unverified_or_paid"


def test_positive_price_blocks_unlimited_entitlement():
    result = assess(offer="Unlimited 1 GB nachbuchen 1,99 €")
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "price_unverified_or_paid"


def test_zero_and_positive_price_still_blocks():
    result = assess(offer="Unlimited 1 GB nachbuchen 0,00 € 2,49 €")
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "price_unverified_or_paid"


def test_unparsed_currency_marker_blocks():
    result = assess(offer="Unlimited 1 GB nachbuchen Preis: €")
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "price_unverified_or_paid"


def test_explicit_zero_euro_remains_valid():
    result = assess(offer="1 GB Highspeed-Datenvolumen nachbuchen 0,00 €")
    assert result["refill_eligible"] is True
    assert result["free_evidence"] == "explicit_free_offer"


def test_plain_current_sml_does_not_prove_unlimited():
    for size in ("S", "M", "L"):
        result = assess(tariff=f"Tarif {size}", offer="1 GB Highspeed-Datenvolumen nachbuchen 0,00 €")
        assert result["refill_eligible"] is False
        assert result["refill_reason"] == "not_unlimited_tariff"


def test_unlimited_at_exactly_one_gb_is_not_eligible():
    result = assess(remaining=1.0)
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "remaining_volume_above_one_gb"


def test_annual_plan_remains_blocked():
    result = assess(tariff="Jahres-Paket S")
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "active_tariff_unverified"
