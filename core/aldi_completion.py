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
RESOURCE_ID_KEYS = {"resourceid", "resource_id", "offerresourceid", "offer_resource_id"}
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


def evaluate_completion(
    *,
    request_payload: Any,
    response_payload: Any,
    http_status: Optional[int],
    account_binding_verified: bool,
    request_was_update_unlimited: bool,
) -> CompletionContract:
    """Evaluate one observed updateUnlimited exchange without guessing semantics.

    Offer binding requires exactly one request resource id and, when the response
    exposes a resource id, an exact match. A successful HTTP status is not enough;
    the response must also contain exactly one explicit terminal-success status and
    exactly one provider operation/order/reference id.
    """
    request_resource = _unique_scalar(request_payload, RESOURCE_ID_KEYS)
    response_resource = _unique_scalar(response_payload, RESOURCE_ID_KEYS)
    operation_id = _unique_scalar(response_payload, OPERATION_ID_KEYS)
    provider_status = _status(response_payload)

    offer_binding_verified = bool(
        request_was_update_unlimited
        and request_resource
        and (response_resource is None or response_resource == request_resource)
    )

    provider_terminal_success = bool(provider_status in TERMINAL_SUCCESS)
    if provider_status in NON_TERMINAL:
        provider_terminal_success = False

    valid_http = isinstance(http_status, int) and 200 <= http_status < 300
    return CompletionContract(
        account_binding_verified=account_binding_verified is True,
        offer_binding_verified=offer_binding_verified,
        provider_operation_bound=bool(operation_id),
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
