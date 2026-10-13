from unittest.mock import Mock

import pytest
import requests

from core.aldi_http_login import AldiHttpLogin, LoginError, LOGIN_LABEL


PHONE = "01520000000"
PASSWORD = "test-only-password"


def _response(payload=None, status=200, url="https://www.alditalk-kundenportal.de/portal/auth/uebersicht/"):
    result = Mock(url=url, status_code=status, headers={})
    result.json.return_value = payload
    return result


def _challenge():
    return {"authId": "private-challenge", "callbacks": [
        {"type": "NameCallback", "input": [{"name": "IDToken1", "value": ""}]},
        {"type": "PasswordCallback", "input": [{"name": "IDToken2", "value": ""}]},
        {"type": "ConfirmationCallback", "input": [{"name": "IDToken3", "value": 0}],
         "output": [{"name": "options", "value": ["sms-login", LOGIN_LABEL, "reset"]}]},
        {"type": "HiddenValueCallback", "input": [{"name": "IDToken4", "value": ""}],
         "output": [{"name": "id", "value": "context"}, {"name": "value", "value": "private-context"}]},
    ]}


def test_account_lock_is_terminal_and_not_reported_as_generic_auth_failure():
    transport = Mock(headers={})
    transport.cookies = requests.cookies.RequestsCookieJar()
    transport.get.return_value = _response()
    locked = {
        "authId": "private-challenge",
        "callbacks": [{
            "type": "TextOutputCallback",
            "output": [{"name": "message", "value": "custom.alditalk.accountLock"}],
        }],
    }
    transport.post.side_effect = [_response(_challenge()), _response(locked)]

    client = AldiHttpLogin(transport)
    with pytest.raises(LoginError, match="^account_locked$"):
        client.login(PHONE, PASSWORD)

    assert client.report["provider_indications"]["account_locked"] is True
    assert client.report["credential_submissions"] == 1
    assert transport.post.call_count == 2  # initial empty challenge + one credential submit
