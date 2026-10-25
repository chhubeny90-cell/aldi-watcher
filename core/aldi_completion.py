"""Fail-closed completion evidence for ALDI TALK on-demand refills.

This module intentionally does not perform a booking. It evaluates already-observed
provider request/response data and returns SUCCESS only when one concrete refill is
bound to the authenticated account, one offer/resource, one provider operation and
an explicit terminal provider status.

Balance changes, banners, SMS/mail and HTTP 2xx alone are supporting evidence only.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Mapping, Optional


TERMINAL_SUCCESS = {"success", "succeeded", "completed", "complete", "fulfilled", "done"}
NON_TERMINAL = {"accepted", "pending", "processing", "queued", "created", "received", "in_progress"}
OPERATION_ID_KEYS = {
    "transactionid", "transaction_id", "operationid", "operation_id",
    "orderid", "order_id", "referenceid", "reference_id",
}
# The current ALDI portal's updateUnlimited payload uses updateOfferResourceID.
# Keep older/generic aliases for observed provider responses, but require exactly
# one value across all aliases so conflicting identifiers fail closed.
RESOURCE_ID_KEYS = {
    "resourceid", "resource_id", "offerresourceid", "offer_resource_id",
    "updateofferresourceid", "update_offer_resource_id",
}
OFFER_ID_KEYS = {"offerid", "offer_id"}
SUBSCRIPTION_ID_KEYS = {"subscriptionid", "subscription_id"}
STATUS_KEYS = {"status", "state", "operationstatus", "operation_status", "orderstatus", "order_status"}


@dataclass(frozen=True)
class CompletionContract:
    account_binding_verified: bool
    offer_binding_verified: bool
    provider_operation_bound: bool
    provider_terminal_success: bool
    provider_operation_id: Optional[str] = None
    provider_resource_id: Optional[str] = None
    provider_status: Optional[str] = None
    http_status: Optional[int] = None

    @property
    def success(self) -> bool:
        return (
            self.account_binding_verified
            and self.offer_binding_verified
            and self.provider_operation_bound
            and self.provider_terminal_success
        )

    @property
    def result(self) -> str:
        return "SUCCESS" if self.success else "UNKNOWN"

    def sanitized(self) -> dict[str, Any]:
        data = asdict(self)
        # Provider identifiers belong in the private durable journal, not reports.
        data["provider_operation_id"] = bool(self.provider_operation_id)
        data["provider_resource_id"] = bool(self.provider_resource_id)
        # Provider status fields may contain unexpected free text. Preserve it
        # only in the encrypted journal; public reports use known states alone.
        data["provider_status"] = (
            self.provider_status
            if self.provider_status in TERMINAL_SUCCESS | NON_TERMINAL else None
        )
        return data


def _walk(value: Any, prefix: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = prefix + (str(key),)
            yield path, child
            yield from _walk(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, prefix + (str(index),))


def _unique_scalar(payload: Any, keys: set[str]) -> Optional[str]:
    values: list[str] = []
    for path, value in _walk(payload):
        if not path or path[-1].casefold() not in keys:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        text = str(value).strip()
        if text and text not in values:
            values.append(text)
    return values[0] if len(values) == 1 else None


def _status(payload: Any) -> Optional[str]:
    values: list[str] = []
    for path, value in _walk(payload):
        if not path or path[-1].casefold() not in STATUS_KEYS or not isinstance(value, str):
            continue
        normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized and normalized not in values:
            values.append(normalized)
    if len(values) != 1:
        return None
    return values[0]


def _response_resource_matches(payload: Any, expected: Optional[str]) -> bool:
    """Omission is allowed; every present alias must be valid and match."""
    for path, value in _walk(payload):
        if path[-1].casefold() not in RESOURCE_ID_KEYS:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return False
        if not str(value).strip() or str(value).strip() != expected:
            return False
    return True


def _operation_status_bound(payload: Any, operation_id: Optional[str], status: Optional[str]) -> bool:
    """Require one record with both direct operation ID and status fields.

    Recursive global uniqueness checks remain in force, but may never assemble
    completion evidence from separate operation/history records.
    """
    if operation_id is None or status is None:
        return False
    records = [payload] + [value for _, value in _walk(payload) if isinstance(value, Mapping)]
    matches = 0
    for record in records:
        if not isinstance(record, Mapping):
            continue
        direct = {key: value for key, value in record.items() if not isinstance(value, (Mapping, list))}
        if _unique_scalar(direct, OPERATION_ID_KEYS) == operation_id and _status(direct) == status:
            matches += 1
    return matches == 1


def evaluate_completion(
    *,
    request_payload: Any,
    response_payload: Any,
    http_status: Optional[int],
    account_binding_verified: bool,
    request_was_update_unlimited: bool,
) -> CompletionContract:
    """Evaluate one observed updateUnlimited exchange without guessing semantics.

    Offer binding requires the concrete request triplet used by the current portal:
    offerId + subscriptionId + updateOfferResourceID/resourceId. If the response
    exposes a resource id it must exactly match the request. A successful HTTP
    status alone is not enough; the response must also contain exactly one explicit
    terminal-success status and exactly one provider operation/order/reference id.
    """
    request_offer = _unique_scalar(request_payload, OFFER_ID_KEYS)
    request_subscription = _unique_scalar(request_payload, SUBSCRIPTION_ID_KEYS)
    request_resource = _unique_scalar(request_payload, RESOURCE_ID_KEYS)
    operation_id = _unique_scalar(response_payload, OPERATION_ID_KEYS)
    provider_status = _status(response_payload)

    offer_binding_verified = bool(
        request_was_update_unlimited
        and request_offer
        and request_subscription
        and request_resource
        and _response_resource_matches(response_payload, request_resource)
    )

    provider_terminal_success = bool(provider_status in TERMINAL_SUCCESS)
    if provider_status in NON_TERMINAL:
        provider_terminal_success = False

    # Acceptance is not a terminal completion, even with a success-looking body.
    valid_http = type(http_status) is int and 200 <= http_status < 300 and http_status != 202
    return CompletionContract(
        account_binding_verified=account_binding_verified is True,
        offer_binding_verified=offer_binding_verified,
        provider_operation_bound=_operation_status_bound(response_payload, operation_id, provider_status),
        provider_terminal_success=bool(valid_http and provider_terminal_success),
        provider_operation_id=operation_id,
        provider_resource_id=request_resource,
        provider_status=provider_status,
        http_status=http_status if isinstance(http_status, int) else None,
    )


def supporting_evidence(*, volume_delta_gb=None, identity_unchanged=None, banner=None, sms=None, email=None):
    """Return diagnostic-only evidence; none of these fields can make SUCCESS."""
    return {
        "volume_delta_gb": volume_delta_gb,
        "identity_unchanged": identity_unchanged,
        "banner_observed": bool(banner),
        "sms_observed": bool(sms),
        "email_observed": bool(email),
    }

