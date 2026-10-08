"""Small, credential-free values passed between LITE and its provider."""

from dataclasses import dataclass
from typing import Optional, Protocol

from core.database import RechargeRecord


@dataclass(frozen=True)
class MailEvent:
    event_id: str
    mailbox: str
    mail_id: str
    received_at: float
    kind: str
    account: str


@dataclass(frozen=True)
class Offer:
    data_mb: int
    price_cents: int
    free_unlimited: bool
    offer_id: Optional[str] = None


@dataclass(frozen=True)
class Snapshot:
    account_verified: bool
    tariff_verified: bool
    offer: Optional[Offer] = None
    pending_booking: bool = False
    remaining_mb: Optional[float] = None


@dataclass(frozen=True)
class Confirmation:
    status: str
    booking_id: Optional[str] = None
    error_class: Optional[str] = None


@dataclass(frozen=True)
class ProcessResult:
    status: str
    action: str
    recharge_id: Optional[str] = None
    error_class: Optional[str] = None


class Provider(Protocol):
    def inspect(self) -> Snapshot: ...
    def book(self, recharge_id: str, offer: Offer) -> Confirmation: ...
    def reconcile(self, record: RechargeRecord) -> Confirmation: ...
    def close(self) -> None: ...
