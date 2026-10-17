"""Fail-closed completion contract for provider-changing recharge operations.

This module intentionally does not know ALDI endpoint names or response fields.
It evaluates already-verified evidence only. A caller must bind provider data to
one local recharge operation before setting any field to True.
"""

from dataclasses import dataclass
from typing import Any, Mapping


TERMINAL_SUCCESS = frozenset({"success", "completed", "fulfilled"})
TERMINAL_FAILURE = frozenset({"failed", "rejected", "cancelled", "canceled"})


@dataclass(frozen=True)
class CompletionEvidence:
    account_binding_verified: bool = False
    offer_binding_verified: bool = False
    provider_operation_bound: bool = False
    provider_terminal_status: str | None = None

    @property
    def normalized_terminal_status(self) -> str | None:
        value = self.provider_terminal_status
        if not isinstance(value, str):
            return None
        value = value.strip().casefold()
        return value or None


def classify_completion(evidence: CompletionEvidence) -> str:
    """Return SUCCESS/FAILED/UNKNOWN without inference from weak signals.

    SUCCESS requires all identity/offer/operation bindings plus an explicit
    terminal success state. A terminal failure is accepted only when the same
    account, offer and provider-operation binding is proven. Everything else is
    UNKNOWN so unresolved operations remain blocked by the durable journal.
    """
    bound = (
        evidence.account_binding_verified is True
        and evidence.offer_binding_verified is True
        and evidence.provider_operation_bound is True
    )
    if not bound:
        return "UNKNOWN"

    status = evidence.normalized_terminal_status
    if status in TERMINAL_SUCCESS:
        return "SUCCESS"
    if status in TERMINAL_FAILURE:
        return "FAILED"
    return "UNKNOWN"


def sanitize_response_shape(value: Any, *, max_depth: int = 6) -> Any:
    """Return field names and value types only, never provider values.

    This is intended for one controlled diagnostic capture of an authenticated
    provider response. It preserves enough structure to discover possible
    transaction/status/resource relationships without writing account numbers,
    IDs, tokens, messages, prices or other values to logs.
    """
    def walk(item: Any, depth: int) -> Any:
        if depth > max_depth:
            return "max_depth"
        if item is None:
            return "null"
        if isinstance(item, bool):
            return "bool"
        if isinstance(item, str):
            return "str"
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return "number"
        if isinstance(item, Mapping):
            return {
                str(key): walk(subvalue, depth + 1)
                for key, subvalue in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, (list, tuple)):
            if not item:
                return []
            shapes = [walk(subvalue, depth + 1) for subvalue in item[:5]]
            # Keep only distinct shapes; never leak list length beyond the small
            # structural sample needed to understand the response schema.
            unique = []
            for shape in shapes:
                if shape not in unique:
                    unique.append(shape)
            return unique
        return type(item).__name__

    return walk(value, 0)
