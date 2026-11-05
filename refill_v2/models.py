"""Typed, non-PII models for the new journal.

Account identifiers are local, non-secret aliases (e.g. 'aldi_primary'),
not telephone numbers, email addresses, user names or authentication tokens.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional


class Provider(str, Enum):
    ALDI = "aldi"
    LIDL = "lidl"


class RefillStatus(str, Enum):
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Blocked(RuntimeError):
    """A fresh, provably free and unique refill is not currently permitted."""


@dataclass(frozen=True)
class OfferProof:
    account_id: str
    exact_one_gb: bool = False
    explicit_zero_price: bool = False
    session_account_verified: bool = False
    provider_permission_verified: bool = False

    @property
    def eligible(self) -> bool:
        return all(value is True for value in (
            self.exact_one_gb,
            self.explicit_zero_price,
            self.session_account_verified,
            self.provider_permission_verified,
        ))


@dataclass(frozen=True)
class CompletionProof:
    operation_id: str
    account_id: str
    receipt_identifier: str
    bound_to_operation: bool = False
    exact_one_gb: bool = False
    explicit_zero_price: bool = False
    official_provider_confirmation: bool = False

    @property
    def verified(self) -> bool:
        return all(value is True for value in (
            self.bound_to_operation,
            self.exact_one_gb,
            self.explicit_zero_price,
            self.official_provider_confirmation,
        ))


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    provider: Provider
    remaining_gb: Optional[Decimal]
    last_checked_at: Optional[str]
    last_refill_at: Optional[str]
    cooldown_until: Optional[str]


@dataclass(frozen=True)
class RefillRecord:
    operation_id: str
    account_id: str
    status: RefillStatus
    created_at: str
    updated_at: str
    receipt_sha256: Optional[str]
