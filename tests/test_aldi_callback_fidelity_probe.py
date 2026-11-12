import hashlib

import pytest

import aldi_callback_fidelity_probe as probe


USER = "01520000000"
PASSWORD = "test-only-password"


def challenge(include_work=True):
    callbacks = [
        {"type": "NameCallback", "input": [{"name": "IDToken1", "value": ""}]},
        {"type": "PasswordCallback", "input": [{"name": "IDToken2", "value": ""}]},
        {
            "type": "ConfirmationCallback",
            "input": [{"name": "IDToken3", "value": 0}],
            "output": [
                {"name": "options", "value": ["custom.alditalk.loginuserbasic.loginbtn"]},
                {"name": "defaultOption", "value": 0},
            ],
        },
        {
            "type": "HiddenValueCallback",
            "input": [{"name": "IDToken4", "value": ""}],
            "output": [
                {"name": "id", "value": "context"},
                {"name": "value", "value": "private-context"},
            ],
        },
    ]
    if include_work:
        callbacks.extend([
            {
                "type": "TextOutputCallback",
                "output": [{"name": "message", "value": 'var work="test"; var difficulty=1;'}],
            },
            {
                "type": "HiddenValueCallback",
                "input": [{"name": "IDToken5", "value": ""}],
                "output": [{"name": "id", "value": "proofOfWorkNonce"}],
            },
        ])
    return {"authId": "private-challenge", "callbacks": callbacks}


def output_value(callback, name):
    return next(
        item["value"]
        for item in callback.get("output", [])
        if item.get("name") == name
    )


def test_prepare_payload_solves_provider_proof_of_work(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", USER)
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", PASSWORD)

    callbacks, normalization = probe._prepare_payload(challenge())

    pow_callback = next(
        callback
        for callback in callbacks
        if callback.get("type") == "HiddenValueCallback"
        and output_value(callback, "id") == "proofOfWorkNonce"
    )
    nonce = pow_callback["input"][0]["value"]
    assert hashlib.sha1(("test" + nonce).encode()).hexdigest().startswith("0")
    assert normalization["proof_of_work_callbacks"] == 1
    assert normalization["proof_of_work_solved"] is True
    assert normalization["hidden_values_copied_from_aldi_output"] == 1


def test_prepare_payload_still_copies_regular_hidden_value(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", USER)
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", PASSWORD)

    callbacks, normalization = probe._prepare_payload(challenge(include_work=False))

    hidden = next(
        callback for callback in callbacks
        if callback.get("type") == "HiddenValueCallback"
    )
    assert hidden["input"][0]["value"] == "private-context"
    assert normalization["proof_of_work_callbacks"] == 0
    assert normalization["proof_of_work_solved"] is False


def test_pow_hidden_callback_without_work_challenge_fails_closed(monkeypatch):
    monkeypatch.setattr(probe.watcher, "ALDI_USER", USER)
    monkeypatch.setattr(probe.watcher, "ALDI_PASS", PASSWORD)
    data = challenge(include_work=False)
    data["callbacks"].append({
        "type": "HiddenValueCallback",
        "input": [{"name": "IDToken5", "value": ""}],
        "output": [{"name": "id", "value": "proofOfWorkNonce"}],
    })

    with pytest.raises(RuntimeError, match="work_challenge_missing"):
        probe._prepare_payload(data)
