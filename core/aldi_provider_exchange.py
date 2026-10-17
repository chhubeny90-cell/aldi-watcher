"""Observe ALDI TALK updateUnlimited traffic emitted by the real portal UI.

The observer never sends a provider request. It only reads Chrome performance-log
entries and DevTools' cached request/response bodies after the already-authorized
UI action. Raw bodies, cookies, tokens and headers are never returned.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit


ALLOWED_HOST_SUFFIX = ".alditalk-kundenportal.de"
UPDATE_PATH_SUFFIX = "/v1/offer/updateUnlimited"
MAX_BODY_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ProviderExchange:
    request_payload: Any
    response_payload: Any
    http_status: Optional[int]
    request_was_update_unlimited: bool
    request_id_present: bool
    response_body_available: bool

    def sanitized_shape(self) -> dict[str, Any]:
        def keys(value):
            if not isinstance(value, dict):
                return []
            return sorted(str(key)[:80] for key in value.keys())[:40]

        return {
            "request_was_update_unlimited": self.request_was_update_unlimited,
            "request_id_present": self.request_id_present,
            "response_body_available": self.response_body_available,
            "http_status": self.http_status,
            "request_top_keys": keys(self.request_payload),
            "response_top_keys": keys(self.response_payload),
        }


def _is_update_url(url: str) -> bool:
    try:
        parsed = urlsplit(url or "")
    except Exception:
        return False
    host = (parsed.hostname or "").casefold()
    return (
        parsed.scheme == "https"
        and (host == "alditalk-kundenportal.de" or host.endswith(ALLOWED_HOST_SUFFIX))
        and parsed.path.rstrip("/").endswith(UPDATE_PATH_SUFFIX)
    )


def _json_body(raw: Any, *, base64_encoded: bool = False) -> Any:
    if not isinstance(raw, str):
        return None
    try:
        data = base64.b64decode(raw, validate=True) if base64_encoded else raw.encode("utf-8")
    except Exception:
        return None
    if len(data) > MAX_BODY_BYTES:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except Exception:
        return None
    return value if isinstance(value, (dict, list)) else None


def clear_performance_log(driver) -> None:
    """Discard pre-action noise. Failure is harmless and must not trigger requests."""
    try:
        driver.get_log("performance")
    except Exception:
        pass


def _cached_response_body(driver, request_id):
    """Read only Chrome's cached response body; never issue or repeat a provider call."""
    try:
        cached = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
    except Exception:
        return None
    if not isinstance(cached, dict):
        return None
    return _json_body(
        cached.get("body"),
        base64_encoded=cached.get("base64Encoded") is True,
    )


def observe_update_unlimited_exchange(driver, timeout: float = 8.0) -> Optional[ProviderExchange]:
    """Return the first observed updateUnlimited request/response pair.

    No click, navigation, refresh or network retry is performed here. DevTools body
    reads operate on data Chrome already received for the UI-triggered request. A
    response body can become readable shortly after responseReceived, so cached
    body reads are retried until the observation deadline without repeating the
    provider request.
    """
    deadline = time.monotonic() + max(0.1, float(timeout))
    request_id = None
    request_payload = None
    http_status = None
    response_seen = False

    while time.monotonic() < deadline:
        try:
            entries = driver.get_log("performance")
        except Exception:
            entries = []

        for entry in entries:
            try:
                message = json.loads(entry.get("message", "{}"))["message"]
                method = message.get("method")
                params = message.get("params", {})
                candidate_id = params.get("requestId")

                if method == "Network.requestWillBeSent" and request_id is None:
                    request = params.get("request", {})
                    if request.get("method") != "POST" or not _is_update_url(request.get("url") or ""):
                        continue
                    if not isinstance(candidate_id, str) or not candidate_id:
                        continue
                    request_id = candidate_id
                    raw = request.get("postData")
                    if not isinstance(raw, str):
                        try:
                            raw = driver.execute_cdp_cmd(
                                "Network.getRequestPostData", {"requestId": request_id}
                            ).get("postData")
                        except Exception:
                            raw = None
                    request_payload = _json_body(raw)

                elif method == "Network.responseReceived" and request_id and candidate_id == request_id:
                    response = params.get("response", {})
                    if not _is_update_url(response.get("url") or ""):
                        continue
                    status = response.get("status")
                    if type(status) in (int, float) and 100 <= status <= 599 and int(status) == status:
                        http_status = int(status)
                    response_seen = True
            except Exception:
                continue

        if request_id and response_seen:
            response_payload = _cached_response_body(driver, request_id)
            if response_payload is not None:
                return ProviderExchange(
                    request_payload=request_payload,
                    response_payload=response_payload,
                    http_status=http_status,
                    request_was_update_unlimited=True,
                    request_id_present=True,
                    response_body_available=True,
                )

        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.25, remaining))

    if request_id:
        return ProviderExchange(
            request_payload=request_payload,
            response_payload=None,
            http_status=http_status,
            request_was_update_unlimited=True,
            request_id_present=True,
            response_body_available=False,
        )
    return None
