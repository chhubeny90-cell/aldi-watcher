from core.completion_contract import (
    CompletionEvidence,
    classify_completion,
    sanitize_response_shape,
)


def test_success_requires_all_bindings_and_terminal_success():
    evidence = CompletionEvidence(
        account_binding_verified=True,
        offer_binding_verified=True,
        provider_operation_bound=True,
        provider_terminal_status="COMPLETED",
    )
    assert classify_completion(evidence) == "SUCCESS"


def test_missing_operation_binding_never_succeeds():
    evidence = CompletionEvidence(
        account_binding_verified=True,
        offer_binding_verified=True,
        provider_operation_bound=False,
        provider_terminal_status="success",
    )
    assert classify_completion(evidence) == "UNKNOWN"


def test_generic_or_nonterminal_status_stays_unknown():
    evidence = CompletionEvidence(
        account_binding_verified=True,
        offer_binding_verified=True,
        provider_operation_bound=True,
        provider_terminal_status="accepted",
    )
    assert classify_completion(evidence) == "UNKNOWN"


def test_bound_terminal_failure_may_resolve_failed():
    evidence = CompletionEvidence(
        account_binding_verified=True,
        offer_binding_verified=True,
        provider_operation_bound=True,
        provider_terminal_status="rejected",
    )
    assert classify_completion(evidence) == "FAILED"


def test_unbound_failure_stays_unknown():
    evidence = CompletionEvidence(
        account_binding_verified=False,
        offer_binding_verified=True,
        provider_operation_bound=True,
        provider_terminal_status="failed",
    )
    assert classify_completion(evidence) == "UNKNOWN"


def test_sanitizer_keeps_structure_but_not_values():
    raw = {
        "transactionId": "secret-operation-123",
        "status": "COMPLETED",
        "resource": {"id": "private-resource", "active": True},
        "amount": 1024,
        "items": [{"name": "1 GB", "price": 0}, {"name": "other", "price": 4.99}],
    }
    shape = sanitize_response_shape(raw)

    assert shape["transactionId"] == "str"
    assert shape["status"] == "str"
    assert shape["resource"] == {"active": "bool", "id": "str"}
    assert shape["amount"] == "number"
    rendered = repr(shape)
    for private_value in ("secret-operation-123", "COMPLETED", "private-resource", "1 GB", "4.99"):
        assert private_value not in rendered


def test_volume_delta_is_not_part_of_completion_contract():
    evidence = CompletionEvidence(
        account_binding_verified=True,
        offer_binding_verified=True,
        provider_operation_bound=False,
        provider_terminal_status=None,
    )
    observed_volume_delta_gb = 1.0
    assert observed_volume_delta_gb > 0
    assert classify_completion(evidence) == "UNKNOWN"
