"""Fail-closed inspection of an already-observed 1 GB free refill offer.

This is NOT a provider receipt and cannot mark any recharge SUCCESS/FAILED.
The browser adapter must prove all values come from the same selected account,
tariff and offer container. Existing core.completion_contract remains authoritative
for terminal provider outcomes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.aldi_accounts import Account


ACCOUNT_ID_PATTERN = re.compile(r"[a-z0-9_]{3,32}\Z")
ONE_GB_PATTERN = re.compile(r"1(?:[,.]0+)?\s*GB\Z", re.IGNORECASE)
GB_IN_TEXT = re.compile(r"(?<!\w)(\d+(?:[,.]\d+)?)\s*GB\b", re.IGNORECASE)
PRICE_PATTERN = re.compile(r"(\d+(?:[,.]\d{1,2})?)\s*(?:€|EUR)\Z", re.IGNORECASE)
PRICE_IN_TEXT = re.compile(r"(?<!\d)(\d+(?:[,.]\d{1,2})?)\s*(?:€|EUR)(?![A-Za-z])", re.IGNORECASE)


def validate_account_id(account_id: str) -> str:
    if not isinstance(account_id, str) or not ACCOUNT_ID_PATTERN.fullmatch(account_id):
        raise ValueError("invalid_account_id")
    return account_id


def _normalized(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_offer_text")
    return " ".join(value.split()).casefold()


def parse_price_cents(label: str) -> int:
    """Accept a single explicit currency amount or the exact word 'kostenlos'."""
    value = _normalized(label)
    if value == "kostenlos":
        return 0
    match = PRICE_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("ambiguous_or_missing_offer_price")
    number = Decimal(match.group(1).replace(",", "."))
    cents = number * 100
    if cents != cents.to_integral_value():
        raise ValueError("invalid_price_precision")
    return int(cents)


@dataclass(frozen=True, slots=True)
class OfferInspection:
    account_id: str
    msisdn_suffix: str
    tariff_name: str
    volume_label: str
    price_label: str
    price_cents: int
    raw_button_text: str

    @classmethod
    def from_observed_ui(
        cls,
        *,
        account_id: str,
        msisdn_suffix: str,
        tariff_name: str,
        volume_label: str,
        price_label: str,
        raw_button_text: str,
    ) -> "OfferInspection":
        return cls(
            account_id=validate_account_id(account_id),
            msisdn_suffix=msisdn_suffix,
            tariff_name=tariff_name,
            volume_label=volume_label,
            price_label=price_label,
            price_cents=parse_price_cents(price_label),
            raw_button_text=raw_button_text,
        )

    def assert_free_1gb_for_account(
        self,
        expected_suffix: str,
        expected_tariff: str,
        *,
        expected_account_id: str,
    ) -> None:
        """Validate strict identity and offer attributes; returns no success receipt.

        Requiring the account_id and exact tariff match prevents a stale session
        from authorizing a different SIM. Both this assertion and a valid
        completion contract are needed in the future provider integration.
        """
        if self.account_id != validate_account_id(expected_account_id):
            raise PermissionError("account_identity_unverified")
        if not (
            isinstance(self.msisdn_suffix, str)
            and re.fullmatch(r"\d{4}", self.msisdn_suffix)
            and isinstance(expected_suffix, str)
            and re.fullmatch(r"\d{4}", expected_suffix)
            and self.msisdn_suffix == expected_suffix
        ):
            raise PermissionError("account_identity_unverified")

        if not _normalized(expected_tariff) or _normalized(self.tariff_name) != _normalized(expected_tariff):
            raise PermissionError("tariff_identity_unverified")

        if not isinstance(self.volume_label, str) or not ONE_GB_PATTERN.fullmatch(
            self.volume_label.strip()
        ):
            raise PermissionError("offer_volume_unverified")

        if type(self.price_cents) is not int or self.price_cents != 0:
            raise PermissionError("paid_offer_blocked")
        if parse_price_cents(self.price_label) != self.price_cents:
            raise PermissionError("offer_price_inconsistent")

        if not isinstance(self.raw_button_text, str):
            raise PermissionError("offer_button_unverified")
        volumes = GB_IN_TEXT.findall(self.raw_button_text)
        if not volumes or any(Decimal(v.replace(",", ".")) != 1 for v in volumes):
            raise PermissionError("offer_button_unverified")
        # A conflicting, paid amount anywhere in the actionable button blocks.
        for amount in PRICE_IN_TEXT.findall(self.raw_button_text):
            if Decimal(amount.replace(",", ".")) != 0:
                raise PermissionError("paid_offer_blocked")

    def assert_for_aldi_account(self, account: "Account", expected_tariff: str) -> None:
        """Adapter for the existing core.aldi_accounts.Account signature."""
        self.assert_free_1gb_for_account(
            expected_suffix=account.account_user[-4:],
            expected_tariff=expected_tariff,
            expected_account_id=account.account_id,
        )
