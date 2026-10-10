import base64
import hashlib
import json
from unittest.mock import Mock

import pytest
import requests

from core.aldi_http_login import (
    AldiHttpLogin, LoginError, LOGIN_LABEL, OVERVIEW, NAVIGATION, AUTH_BASE,
    phone_identifier, prepare_callbacks,
    result_diagnostics,
)

PHONE = "01520000000"
PASSWORD = "test-only-password"


def challenge():
    return {"authId": "private-challenge", "callbacks": [
        {"type": "NameCallback", "input": [{"name": "IDToken1", "value": ""}]},
        {"type": "PasswordCallback", "input": [{"name": "IDToken2", "value": ""}]},
        {"type": "ConfirmationCallback", "input": [{"name": "IDToken3", "value": 0}],
         "output": [{"name": "options", "value": ["sms-login", LOGIN_LABEL, "reset"]}]},
        {"type": "HiddenValueCallback", "input": [{"name": "IDToken4", "value": ""}],
         "output": [{"name": "id", "value": "context"}, {"name": "value", "value": "private-context"}]},
    ]}


def response(url=OVERVIEW, status=200, payload=None, headers=None):
    result = Mock(url=url, status_code=status, headers=headers or {})
    result.json.return_value = payload
    return result


def session():
    result = Mock(headers={})
    result.cookies = requests.cookies.RequestsCookieJar()
    result.cookies.set("lgrs_id", base64.b64encode(PHONE.encode()).decode(),
                       domain="www.alditalk-kundenportal.de", path="/")
    return result


def test_phone_formats_normalize_without_guessing():
    assert phone_identifier("+49 1520000000") == PHONE
    assert phone_identifier("0049 1520000000") == PHONE
    with pytest.raises(LoginError):
        phone_identifier("A-PRIVATE")


def test_callbacks_preserve_hidden_values_and_select_password_option():
    original = challenge()
    payload = prepare_callbacks(original, PHONE, PASSWORD)
    callbacks = payload["callbacks"]
    assert callbacks[0]["input"][0]["value"] == PHONE
    assert callbacks[1]["input"][0]["value"] == PASSWORD
    assert callbacks[2]["input"][0]["value"] == 1
    assert callbacks[3]["input"][0]["value"] == "private-context"
    assert original["callbacks"][0]["input"][0]["value"] == ""


def test_provider_work_challenge_is_filled():
    data = challenge()
    data["callbacks"].extend([
        {"type": "TextOutputCallback", "output": [{"name": "message", "value": 'var work="test"; var difficulty=1;'}]},
        {"type": "HiddenValueCallback", "output": [{"name": "id", "value": "proofOfWorkNonce"}],
         "input": [{"name": "IDToken5", "value": ""}]},
    ])
    payload = prepare_callbacks(data, PHONE, PASSWORD)
    nonce = payload["callbacks"][-1]["input"][0]["value"]
    assert hashlib.sha1(("test" + nonce).encode()).hexdigest().startswith("0")


def test_missing_password_option_cannot_select_sms():
    data = challenge()
    data["callbacks"][2]["output"][0]["value"] = ["sms-login", "reset"]
    with pytest.raises(LoginError, match="password_login_option_unverified"):
        prepare_callbacks(data, PHONE, PASSWORD)


def test_external_redirect_is_blocked_before_request():
    transport = session()
    transport.get.return_value = response(status=302, headers={"Location": "https://attacker.invalid"})
    with pytest.raises(LoginError, match="unexpected_redirect_origin"):
        AldiHttpLogin(transport)._get(OVERVIEW)
    assert transport.get.call_count == 1


def test_auth_post_redirect_does_not_forward_credentials():
    transport = session()
    transport.post.return_value = response(status=307, headers={"Location": "https://attacker.invalid"})
    with pytest.raises(LoginError, match="authentication_http_error"):
        AldiHttpLogin(transport)._authenticate({"private": PASSWORD})
    assert transport.post.call_count == 1
    assert transport.post.call_args.kwargs["allow_redirects"] is False


def test_verified_login_requires_redirects_and_protected_account_json():
    transport = session()
    transport.post.side_effect = [response(payload=challenge()),
        response(payload={"successUrl": AUTH_BASE + "/success", "tokenId": "private-token"})]
    transport.get.side_effect = [response(), response(), response(),
        response(url=NAVIGATION, payload={"userDetails": {"subscriptions": [{"contractId": "private-contract"}]}})]
    client = AldiHttpLogin(transport)
    assert client.login(PHONE, PASSWORD) is True
    assert client.report["account_match"] is True
    assert client.report["credential_submissions"] == 1
    assert transport.post.call_count == 2
    assert "private" not in json.dumps(client.report)
    assert PHONE not in json.dumps(client.report)
    assert PASSWORD not in json.dumps(client.report)


def test_account_mismatch_never_reads_other_subscription():
    transport = session()
    transport.cookies.clear()
    transport.cookies.set("lgrs_id", base64.b64encode(b"01529999999").decode(),
                          domain="www.alditalk-kundenportal.de", path="/")
    transport.post.side_effect = [response(payload=challenge()), response(payload={"successUrl": "/success"})]
    transport.get.return_value = response()
    client = AldiHttpLogin(transport)
    with pytest.raises(LoginError, match="account_mismatch"):
        client.login(PHONE, PASSWORD)
    assert client.report["login_ok"] is False
    assert transport.get.call_count == 3


def test_incomplete_auth_is_not_retried_or_printed():
    transport = session()
    transport.get.return_value = response()
    transport.post.side_effect = [response(payload=challenge()), response(payload={"message": PASSWORD})]
    client = AldiHttpLogin(transport)
    with pytest.raises(LoginError, match="authentication_not_completed"):
        client.login(PHONE, PASSWORD)
    assert transport.post.call_count == 2
    assert client.report["credential_submissions"] == 1
    assert PASSWORD not in json.dumps(client.report)


def test_provider_error_indications_never_return_raw_message():
    result = {"callbacks": [{"type": "TextOutputCallback", "output": [
        {"name": "message", "value": "custom.alditalk.accountLock: PRIVATE_ACCOUNT gesperrt"}]}]}
    diagnostics = result_diagnostics(result)
    assert diagnostics["provider_indications"]["account_locked"] is True
    assert "PRIVATE_ACCOUNT" not in json.dumps(diagnostics)


def test_additional_verification_is_identified_without_selecting_it():
    diagnostics = result_diagnostics({"message": "Bitte SMS-Code PRIVATE_CODE eingeben"})
    assert diagnostics["provider_indications"]["additional_verification"] is True
    assert "PRIVATE_CODE" not in json.dumps(diagnostics)
