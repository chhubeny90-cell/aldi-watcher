"""Offline-only candidate assessment for NettoKOM LIFT free 1-GB refill.

No I/O, authentication, provider requests or booking. Never authorizes live access.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional


@dataclass(frozen=True)
class LiftObservation:
    account_verified: bool = False
    active_tariff: str = ""
    remaining_gb: Optional[str] = None
    offer_size_gb: Optional[str] = None
    offer_price_eur: Optional[str] = None
    offer_candidate_count: int = 0
    offer_enabled: bool = False
    unresolved_transaction: bool = True
    conflicting_terms: bool = True


@dataclass(frozen=True)
class LiftAssessment:
    simulated_offer_eligible: bool
    reason: str
    booking_authorized: bool = False


def _decimal(value: Optional[str]) -> Optional[Decimal]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        number = Decimal(value.strip().replace(",", "."))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def assess_lift(observation: LiftObservation) -> LiftAssessment:
    """Fail closed; even valid test data does not permit live booking."""
    if observation.account_verified is not True:
        return LiftAssessment(False, "account_unverified")
    if observation.active_tariff.strip().casefold() not in {"lift s", "lift m", "lift l"}:
        return LiftAssessment(False, "active_lift_tariff_unverified")
    remaining = _decimal(observation.remaining_gb)
    if remaining is None or remaining < 0:
        return LiftAssessment(False, "remaining_volume_unverified")
    if remaining >= 1:
        return LiftAssessment(False, "threshold_not_reached")
    if observation.unresolved_transaction is not False:
        return LiftAssessment(False, "unresolved_transaction")
    if observation.conflicting_terms is not False:
        return LiftAssessment(False, "conflicting_offer_terms")
    if type(observation.offer_candidate_count) is not int or observation.offer_candidate_count != 1:
        return LiftAssessment(False, "offer_ambiguous")
    if _decimal(observation.offer_size_gb) != Decimal("1"):
        return LiftAssessment(False, "not_exactly_one_gb")
    if _decimal(observation.offer_price_eur) != Decimal("0"):
        return LiftAssessment(False, "price_not_explicit_zero")
    if observation.offer_enabled is not True:
        return LiftAssessment(False, "offer_disabled")
    return LiftAssessment(True, "offline_candidate_only", booking_authorized=False)
