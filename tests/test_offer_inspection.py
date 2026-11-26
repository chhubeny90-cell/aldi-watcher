"""Offline regression tests for the read-only offer-inspection contract."""

import pytest

from core.aldi_accounts import Account
from core.offer_inspection import (
    OfferInspection,
    parse_price_cents,
    validate_account_id,
)


def valid_offer(**overrides):
    data = dict(
        account_id="account_a",
        msisdn_suffix="1234",
        tariff_name="Unlimited on Demand S",
        volume_label="1 GB",
        price_label="0,00 €",
        raw_button_text="+ 1 GB Refill",
    )
    data.update(overrides)
    return OfferInspection.from_observed_ui(**data)


def assert_allowed(offer):
    offer.assert_free_1gb_for_account(
        "1234", "Unlimited on Demand S", expected_account_id="account_a"
    )


def test_exact_free_1gb_offer_is_eligible_but_not_a_receipt():
    offer = valid_offer()
    assert offer.price_cents == 0
    assert_allowed(offer)
    assert not hasattr(offer, "confirmed")
    assert not hasattr(offer, "recharge_id")


@pytest.mark.parametrize("value", ["0,00 €", "0.00 EUR", "kostenlos"])
def test_explicit_zero_price_formats(value):
    assert parse_price_cents(value) == 0
    assert_allowed(valid_offer(price_label=value))


@pytest.mark.parametrize("price", ["4,99 €", "0,99 EUR", "1 €", "0,00 € zzgl. Gebühr", "0 € / 4 €", "0", "nachbuchen", "gratis"])
def test_paid_or_ambiguous_price_never_authorizes(price):
    try:
        offer = valid_offer(price_label=price)
    except ValueError:
        return
    with pytest.raises(PermissionError, match="paid_offer_blocked"):
        assert_allowed(offer)


@pytest.mark.parametrize("button", [
    "1 GB - 4,99 €",
    "1 GB oder 2 GB",
    "Nachbuchen",
    "1 GB + 0,00 € und 1,00 EUR",
])
def test_ambiguous_button_blocks(button):
    with pytest.raises(PermissionError):
        assert_allowed(valid_offer(raw_button_text=button))


@pytest.mark.parametrize("volume", ["11 GB", "1 GB + 2 GB", "1000 MB", "1 GB / 10 GB", "2 GB"])
def test_wrong_volume_blocked(volume):
    with pytest.raises(PermissionError, match="offer_volume_unverified"):
        assert_allowed(valid_offer(volume_label=volume))


def test_tariff_substring_does_not_match():
    with pytest.raises(PermissionError, match="tariff_identity_unverified"):
        assert_allowed(valid_offer(tariff_name="Unlimited on Demand S Plus"))


def test_wrong_sim_and_account_id_blocked_without_leaking_pii():
    with pytest.raises(PermissionError, match="account_identity_unverified") as exc:
        assert_allowed(valid_offer(msisdn_suffix="9999"))
    assert "9999" not in str(exc.value)
    with pytest.raises(PermissionError, match="account_identity_unverified"):
        assert_allowed(valid_offer(account_id="account_b"))


@pytest.mark.parametrize("account_id", ["../escape", "a", "a/b", "Übersicht", "account-a", "a" * 33])
def test_unsafe_account_ids_rejected(account_id):
    with pytest.raises(ValueError, match="invalid_account_id"):
        validate_account_id(account_id)


def test_explicit_price_label_must_match_price_cents():
    from dataclasses import replace

    with pytest.raises(PermissionError, match="offer_price_inconsistent"):
        assert_allowed(replace(valid_offer(), price_label="5,00 €"))
    with pytest.raises(PermissionError, match="paid_offer_blocked"):
        assert_allowed(replace(valid_offer(), price_cents=True))


def test_existing_aldi_account_adapter_uses_private_account_number_without_logging():
    account = Account(
        account_id="account_a",
        account_user="+4915211111234",
        login_user="+4915211111234",
        password="test-only",
    )
    valid_offer().assert_for_aldi_account(account, "Unlimited on Demand S")
    with pytest.raises(PermissionError, match="account_identity_unverified"):
        valid_offer(msisdn_suffix="5678").assert_for_aldi_account(
            account, "Unlimited on Demand S"
        )
