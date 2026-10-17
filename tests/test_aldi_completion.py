import pytest

from core.aldi_completion import evaluate_completion, supporting_evidence


def test_success_requires_all_four_gates():
    result = evaluate_completion(
        request_payload={"resourceId": "offer-1"},
        response_payload={
            "transactionId": "tx-1",
            "resourceId": "offer-1",
            "status": "COMPLETED",
        },
        http_status=200,
        account_binding_verified=True,
        request_was_update_unlimited=True,
    )
    assert result.success is True
    assert result.result == "SUCCESS"


@pytest.mark.parametrize(
    "response,http_status,account_bound,request_is_update",
    [
        ({"transactionId": "tx-1", "resourceId": "offer-1", "status": "COMPLETED"}, 200, False, True),
        ({"transactionId": "tx-1", "resourceId": "other", "status": "COMPLETED"}, 200, True, True),
        ({"resourceId": "offer-1", "status": "COMPLETED"}, 200, True, True),
        ({"transactionId": "tx-1", "resourceId": "offer-1", "status": "ACCEPTED"}, 202, True, True),
        ({"transactionId": "tx-1", "resourceId": "offer-1", "status": "COMPLETED"}, 500, True, True),
        ({"transactionId": "tx-1", "resourceId": "offer-1", "status": "COMPLETED"}, 200, True, False),
    ],
)
def test_missing_or_nonterminal_gate_stays_unknown(response, http_status, account_bound, request_is_update):
    result = evaluate_completion(
        request_payload={"resourceId": "offer-1"},
        response_payload=response,
        http_status=http_status,
        account_binding_verified=account_bound,
        request_was_update_unlimited=request_is_update,
    )
    assert result.success is False
    assert result.result == "UNKNOWN"


def test_ambiguous_operation_ids_are_not_bound():
    result = evaluate_completion(
        request_payload={"resourceId": "offer-1"},
        response_payload={
            "transactionId": "tx-1",
            "orderId": "order-2",
            "resourceId": "offer-1",
            "status": "SUCCESS",
        },
        http_status=200,
        account_binding_verified=True,
        request_was_update_unlimited=True,
    )
    assert result.provider_operation_bound is False
    assert result.result == "UNKNOWN"


def test_ambiguous_statuses_are_not_terminal_success():
    result = evaluate_completion(
        request_payload={"resourceId": "offer-1"},
        response_payload={
            "transactionId": "tx-1",
            "resourceId": "offer-1",
            "status": "COMPLETED",
            "details": {"state": "PROCESSING"},
        },
        http_status=200,
        account_binding_verified=True,
        request_was_update_unlimited=True,
    )
    assert result.provider_terminal_success is False
    assert result.result == "UNKNOWN"


def test_response_may_omit_resource_if_request_has_one():
    result = evaluate_completion(
        request_payload={"resourceId": "offer-1"},
        response_payload={"transactionId": "tx-1", "status": "SUCCESS"},
        http_status=200,
        account_binding_verified=True,
        request_was_update_unlimited=True,
    )
    assert result.offer_binding_verified is True
    assert result.result == "SUCCESS"


def test_sanitized_report_never_exposes_provider_ids():
    result = evaluate_completion(
        request_payload={"resourceId": "secret-offer"},
        response_payload={"transactionId": "secret-tx", "status": "FULFILLED"},
        http_status=200,
        account_binding_verified=True,
        request_was_update_unlimited=True,
    )
    safe = result.sanitized()
    assert safe["provider_operation_id"] is True
    assert safe["provider_resource_id"] is True
    assert "secret" not in repr(safe)


def test_balance_sms_banner_and_email_are_diagnostic_only():
    evidence = supporting_evidence(
        volume_delta_gb=1.0,
        identity_unchanged=True,
        banner="success",
        sms="1 GB gebucht",
        email="Bestätigung",
    )
    assert evidence["volume_delta_gb"] == 1.0
    assert evidence["identity_unchanged"] is True
    assert all(evidence[key] is True for key in ("banner_observed", "sms_observed", "email_observed"))
