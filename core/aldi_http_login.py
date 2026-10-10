"""Browser-free ALDI login; secrets and session values stay in memory.

Protocol reference: JonasJoKuJonas/homeassistant-AldiTalk, MIT, revision
recorded in docs/aldi-http-login.md. Only login POSTs and read-only GETs exist.
"""
import base64
import copy
import hashlib
import re
import time
from urllib.parse import urljoin, urlsplit

import requests

AUTH_BASE = "https://login.alditalk-kundenbetreuung.de"
AUTH_API = AUTH_BASE + "/signin/json/authenticate"
PORTAL_BASE = "https://www.alditalk-kundenportal.de"
OVERVIEW = PORTAL_BASE + "/portal/auth/uebersicht/"
NAVIGATION = PORTAL_BASE + "/scs/bff/scs-207-customer-master-data-bff/customer-master-data/v1/navigation-list"
ALLOWED_HOSTS = {
    "login.alditalk-kundenbetreuung.de", "www.alditalk-kundenbetreuung.de",
    "www.alditalk-kundenportal.de",
}
LOGIN_LABEL = "custom.alditalk.loginuserbasic.loginbtn"


class LoginError(Exception):
    """Contains a fixed reason code, never upstream text or URLs."""


def phone_identifier(value):
    value = re.sub(r"[\s()-]", "", value or "")
    if value.startswith("+49"):
        value = "0" + value[3:]
    elif value.startswith("0049"):
        value = "0" + value[4:]
    if not re.fullmatch(r"0\d{9,13}", value):
        raise LoginError("phone_identifier_required")
    return value


def trusted_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise LoginError("unexpected_redirect_origin")
    return url


def _output(callback, name):
    matches = [x.get("value") for x in callback.get("output", [])
               if isinstance(x, dict) and x.get("name") == name]
    return matches[0] if len(matches) == 1 else None


def result_diagnostics(result):
    """Reduce provider messages to indications, never persist their contents."""
    callbacks = result.get("callbacks")
    callbacks = callbacks if isinstance(callbacks, list) else []
    messages = [result.get("message"), result.get("detail")]
    messages.extend(_output(c, "message") for c in callbacks
                    if isinstance(c, dict) and c.get("type") == "TextOutputCallback")
    text = " ".join(m.casefold() for m in messages if isinstance(m, str))
    known_types = {"NameCallback", "PasswordCallback", "HiddenValueCallback",
                   "TextOutputCallback", "ConfirmationCallback", "ChoiceCallback"}
    return {
        "returned_callback_count": len(callbacks),
        "returned_callback_types": sorted({c.get("type") if c.get("type") in known_types
                                           else "OtherCallback" for c in callbacks if isinstance(c, dict)}),
        "provider_indications": {
            "account_locked": any(s in text for s in ("accountlock", "account locked", "gesperrt", "zu viele versuche")),
            "credential_problem": any(s in text for s in ("invalid credential", "incorrect credential", "wrong credential", "invalidlogin", "passwort falsch", "falsches passwort", "stimmen nicht überein")),
            "required_fields": any(s in text for s in ("required field", "pflichtfeld", "ausfüllen", "ausfuellen", "field is required")),
            "technical_error": any(s in text for s in ("technical error", "technischer fehler", "temporarily unavailable", "service unavailable")),
            "additional_verification": any(s in text for s in ("sms-code", "sms code", "sms-tan", "einmalpasswort", "one-time password", "bestätigungscode")),
            "error_message": any(s in text for s in ("error", "failed", "invalid", "fehler", "fehlgeschlagen")),
        },
    }


def _proof_of_work(callbacks):
    messages = [_output(c, "message") for c in callbacks
                if c.get("type") == "TextOutputCallback"]
    for message in messages:
        if not isinstance(message, str):
            continue
        work = re.search(r'var\s+work\s*=\s*[\"\']([^\"\']+)[\"\']', message)
        difficulty = re.search(r"var\s+difficulty\s*=\s*(\d+)", message)
        if work:
            if not difficulty or not 1 <= int(difficulty[1]) <= 5:
                raise LoginError("unsupported_work_difficulty")
            target = "0" * int(difficulty[1])
            deadline = time.monotonic() + 10
            for nonce in range(10_000_000):
                if nonce % 4096 == 0 and time.monotonic() > deadline:
                    raise LoginError("work_deadline_exceeded")
                if hashlib.sha1(f"{work[1]}{nonce}".encode()).hexdigest().startswith(target):
                    return str(nonce)
            raise LoginError("work_deadline_exceeded")
    return None


def prepare_callbacks(challenge, username, password):
    """Fill known callback types; never choose SMS, reset or other actions."""
    if not isinstance(challenge, dict) or not challenge.get("authId"):
        raise LoginError("auth_challenge_missing")
    callbacks = copy.deepcopy(challenge.get("callbacks"))
    if not isinstance(callbacks, list) or not all(isinstance(c, dict) for c in callbacks):
        raise LoginError("callback_schema_unexpected")
    counts = {kind: sum(c.get("type") == kind for c in callbacks)
              for kind in ("NameCallback", "PasswordCallback", "ConfirmationCallback")}
    if any(count != 1 for count in counts.values()):
        raise LoginError("credential_challenge_unexpected")
    pow_solution = _proof_of_work(callbacks)
    for callback in callbacks:
        kind = callback.get("type")
        if kind == "TextOutputCallback":
            continue
        inputs = callback.get("input")
        if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
            raise LoginError("callback_input_unexpected")
        if kind == "NameCallback":
            value = username
        elif kind == "PasswordCallback":
            value = password
        elif kind == "ConfirmationCallback":
            options = _output(callback, "options")
            if not isinstance(options, list) or options.count(LOGIN_LABEL) != 1:
                raise LoginError("password_login_option_unverified")
            value = options.index(LOGIN_LABEL)
        elif kind == "HiddenValueCallback":
            if _output(callback, "id") == "proofOfWorkNonce":
                if pow_solution is None:
                    raise LoginError("work_challenge_missing")
                value = pow_solution
            else:
                value = _output(callback, "value")
                if value is None:
                    raise LoginError("hidden_callback_value_missing")
        else:
            raise LoginError("additional_authentication_required")
        inputs[0]["value"] = value
    return {"authId": challenge["authId"], "callbacks": callbacks}


class AldiHttpLogin:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        })
        self.report = {"login_ok": False, "account_match": False,
                       "credential_submissions": 0, "phase": "not_started"}

    def _get(self, url, **kwargs):
        # Inspect every redirect before requesting it. POSTs never follow redirects.
        for _ in range(12):
            trusted_url(url)
            response = self.session.get(url, allow_redirects=False, timeout=20, **kwargs)
            kwargs = {}
            self.report["http_status"] = response.status_code
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise LoginError("redirect_location_missing")
                url = urljoin(url, location)
                continue
            if response.status_code != 200:
                raise LoginError("provider_http_error")
            return response
        raise LoginError("redirect_limit_exceeded")

    def _authenticate(self, payload):
        response = self.session.post(AUTH_API,
            params={"realm": "/alditalk", "authIndexType": "service", "authIndexValue": "Login"},
            json=payload, allow_redirects=False, timeout=20,
            headers={"Accept-API-Version": "protocol=1.0,resource=2.1",
                     "Content-Type": "application/json", "X-Username": "anonymous",
                     "X-Password": "anonymous", "X-NoSession": "true",
                     "Origin": AUTH_BASE, "Referer": AUTH_BASE + "/signin/XUI/"})
        self.report["http_status"] = response.status_code
        if response.status_code != 200:
            raise LoginError("authentication_http_error")
        try:
            result = response.json()
        except ValueError:
            raise LoginError("authentication_response_not_json") from None
        if not isinstance(result, dict):
            raise LoginError("authentication_response_unexpected")
        return result

    def login(self, phone, password):
        phone = phone_identifier(phone)
        if not password:
            raise LoginError("password_missing")
        self.report["phase"] = "portal_start"
        self._get(OVERVIEW)
        self.report["phase"] = "auth_challenge"
        challenge = self._authenticate({})
        self.report["phase"] = "prepare_callbacks"
        payload = prepare_callbacks(challenge, phone, password)
        self.report["phase"] = "credential_submit"
        self.report["credential_submissions"] += 1
        result = self._authenticate(payload)
        self.report.update(result_diagnostics(result))
        self.report["auth_token_received"] = bool(result.get("tokenId"))
        success_url = result.get("successUrl")
        self.report["success_url_received"] = bool(success_url)
        if not isinstance(success_url, str) or not success_url:
            raise LoginError("authentication_not_completed")
        self.report["phase"] = "oauth_redirects"
        self._get(urljoin(AUTH_BASE, success_url))
        response = self._get(OVERVIEW)
        if urlsplit(response.url).hostname != urlsplit(PORTAL_BASE).hostname:
            raise LoginError("portal_session_unverified")
        self.report["phase"] = "account_verification"
        # The portal's own current-account cookie identifies the selected SIM.
        cookies = [c.value for c in self.session.cookies if c.name == "lgrs_id"
                   and c.domain.lstrip(".") in ALLOWED_HOSTS]
        if len(set(cookies)) != 1:
            raise LoginError("account_cookie_unverified")
        try:
            encoded = cookies[0] + "=" * (-len(cookies[0]) % 4)
            account = base64.b64decode(encoded, validate=True).decode()
            matches = phone_identifier(account) == phone
        except (ValueError, UnicodeDecodeError, LoginError):
            raise LoginError("account_cookie_unverified") from None
        self.report["account_match"] = matches
        if not matches:
            raise LoginError("account_mismatch")
        response = self._get(NAVIGATION, params={"msisdn": account},
                             headers={"Accept": "application/json", "Referer": OVERVIEW})
        try:
            subscriptions = response.json()["userDetails"]["subscriptions"]
        except (ValueError, KeyError, TypeError):
            raise LoginError("protected_account_response_unverified") from None
        if not isinstance(subscriptions, list) or not subscriptions:
            raise LoginError("protected_account_response_unverified")
        self.report["subscription_count"] = len(subscriptions)
        self.report["login_ok"] = True
        self.report["phase"] = "complete"
        return True

    def close(self):
        self.session.close()
