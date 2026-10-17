import json
from unittest.mock import Mock

from core import aldi_provider_exchange as exchange


def _entry(method, params):
    return {"message": json.dumps({"message": {"method": method, "params": params}})}


def test_cached_response_body_is_retried_without_repeating_provider_request(monkeypatch):
    driver = Mock()
    url = (
        "https://www.alditalk-kundenportal.de/scs/bff/"
        "scs-209-selfcare-dashboard-bff/selfcare-dashboard/v1/offer/updateUnlimited"
    )
    request_id = "req-1"
    driver.get_log.side_effect = [
        [
            _entry("Network.requestWillBeSent", {
                "requestId": request_id,
                "request": {
                    "method": "POST",
                    "url": url,
                    "postData": json.dumps({"resourceId": "offer-1"}),
                },
            }),
            _entry("Network.responseReceived", {
                "requestId": request_id,
                "response": {"url": url, "status": 200},
            }),
        ],
        [],
    ]
    driver.execute_cdp_cmd.side_effect = [
        RuntimeError("body not complete yet"),
        {"body": json.dumps({"transactionId": "tx-1", "status": "COMPLETED"}),
         "base64Encoded": False},
    ]

    ticks = iter([0.0, 0.0, 0.05, 0.1, 0.15])
    monkeypatch.setattr(exchange.time, "monotonic", lambda: next(ticks, 0.15))
    monkeypatch.setattr(exchange.time, "sleep", lambda *_: None)

    observed = exchange.observe_update_unlimited_exchange(driver, timeout=1.0)

    assert observed is not None
    assert observed.request_payload == {"resourceId": "offer-1"}
    assert observed.response_payload == {"transactionId": "tx-1", "status": "COMPLETED"}
    assert observed.http_status == 200
    assert observed.response_body_available is True
    assert driver.execute_cdp_cmd.call_count == 2
    assert all(
        call.args[0] == "Network.getResponseBody"
        for call in driver.execute_cdp_cmd.call_args_list
    )


def test_update_url_rejects_wrong_host_even_with_matching_path():
    assert exchange._is_update_url(
        "https://evil.example/v1/offer/updateUnlimited"
    ) is False
