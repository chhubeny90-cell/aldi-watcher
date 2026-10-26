"""Existing ALDI sessions are verified without another credential submission."""
import base64
import json
from unittest.mock import Mock

import pytest
import requests

from core.aldi_http_login import (
    AldiHttpLogin, LoginError, AUTH_BASE, NAVIGATION, OVERVIEW,
)


PHONE = "01520000000"


def response(url=OVERVIEW, status=200, payload=None, headers=None):
    result = Mock(url=url, status_code=status, headers=headers or {})
    result.json.return_value = payload
    return result


def transport(account=PHONE):
    session = Mock(headers={})
    session.cookies = requests.cookies.RequestsCookieJar()
    session.cookies.set(
        "lgrs_id", base64.b64encode(account.encode()).decode(),
        domain="www.alditalk-kundenportal.de", path="/", secure=True,
    )
    session.post.side_effect = AssertionError("session reuse must not submit credentials")
    session.get.side_effect = [
        response(),
        response(url=NAVIGATION, payload={
            "userDetails": {"subscriptions": [{"contractId": "PRIVATE_CONTRACT"}]},
        }),
    ]
    return session


@pytest.mark.parametrize("phone", [PHONE, "+49" + PHONE[1:], "0049" + PHONE[1:]])
def test_valid_saved_session_uses_only_protected_gets(phone):
    session = transport()
    client = AldiHttpLogin(session)
    assert client.verify_session(phone) is True
    assert [call.args[0] for call in session.get.call_args_list] == [OVERVIEW, NAVIGATION]
    assert session.get.call_args.kwargs["params"] == {"msisdn": PHONE}
    assert all(call.kwargs["allow_redirects"] is False for call in session.get.call_args_list)
    session.post.assert_not_called()
    assert client.report["credential_submissions"] == 0
    assert client.report["login_ok"] is True
    assert client.report["account_match"] is True
    assert client.report["subscription_count"] == 1
    assert client.report["phase"] == "complete"
    assert PHONE not in json.dumps(client.report)
    assert "PRIVATE_CONTRACT" not in json.dumps(client.report)


def test_saved_session_for_wrong_sim_does_not_read_subscription():
    session = transport("01529999999")
    client = AldiHttpLogin(session)
    with pytest.raises(LoginError, match="^account_mismatch$"):
        client.verify_session(PHONE)
    assert session.get.call_count == 1
    session.post.assert_not_called()
    assert client.report["login_ok"] is False
    assert client.report["account_match"] is False


def test_expired_session_redirect_is_reported_without_reauthentication():
    session = transport()
    signin = AUTH_BASE + "/signin/XUI/"
    session.get.side_effect = [
        response(status=302, headers={"Location": signin}),
        response(url=signin),
    ]
    client = AldiHttpLogin(session)
    with pytest.raises(LoginError, match="^portal_session_unverified$"):
        client.verify_session(PHONE)
    session.post.assert_not_called()
    assert session.get.call_count == 2
    assert client.report["credential_submissions"] == 0
    assert client.report["login_ok"] is False


def test_foreign_redirect_is_rejected_before_contact():
    session = transport()
    session.get.side_effect = [response(status=302, headers={
        "Location": "https://attacker.invalid/PRIVATE_REDIRECT",
    })]
    client = AldiHttpLogin(session)
    with pytest.raises(LoginError, match="^unexpected_redirect_origin$"):
        client.verify_session(PHONE)
    assert session.get.call_count == 1
    session.post.assert_not_called()
    assert "PRIVATE_REDIRECT" not in json.dumps(client.report)


def test_provider_error_is_not_mistaken_for_session_expiry():
    session = transport()
    session.get.side_effect = [response(status=503)]
    client = AldiHttpLogin(session)
    with pytest.raises(LoginError, match="^provider_http_error$"):
        client.verify_session(PHONE)
    session.post.assert_not_called()
    assert client.report["login_ok"] is False


@pytest.mark.parametrize("payload", [None, {}, {"userDetails": None},
                                     {"userDetails": {"subscriptions": []}}])
def test_session_requires_nonempty_protected_subscription_response(payload):
    session = transport()
    session.get.side_effect = [response(), response(url=NAVIGATION, payload=payload)]
    client = AldiHttpLogin(session)
    with pytest.raises(LoginError, match="^protected_account_response_unverified$"):
        client.verify_session(PHONE)
    session.post.assert_not_called()
    assert client.report["login_ok"] is False
    assert "subscription_count" not in client.report


@pytest.mark.parametrize("failure", [
    "expired", "provider_error", "invalid_phone", "missing_cookie",
])
def test_failed_reverification_clears_previous_success(failure):
    session = transport()
    client = AldiHttpLogin(session)
    assert client.verify_session(PHONE) is True
    if failure == "expired":
        session.get.side_effect = [response(url=AUTH_BASE + "/signin/XUI/")]
    elif failure == "provider_error":
        session.get.side_effect = [response(status=503)]
    else:
        session.get.side_effect = [response()]
    if failure == "missing_cookie":
        session.cookies.clear()
    with pytest.raises(LoginError):
        client.verify_session("invalid" if failure == "invalid_phone" else PHONE)
    assert client.report["login_ok"] is False
    assert client.report["account_match"] is False
    assert "subscription_count" not in client.report
    assert client.report["phase"] != "complete"
    session.post.assert_not_called()


def test_timeout_cannot_trigger_credential_submission():
    session = transport()
    session.get.side_effect = requests.Timeout("PRIVATE_TIMEOUT")
    client = AldiHttpLogin(session)
    with pytest.raises(requests.Timeout):
        client.verify_session(PHONE)
    session.post.assert_not_called()
    assert client.report["login_ok"] is False
    assert "PRIVATE_TIMEOUT" not in json.dumps(client.report)
