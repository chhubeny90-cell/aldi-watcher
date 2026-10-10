"""Compare ALDI's initial auth request with one sanitized continuation POST.

This diagnostic never logs secrets, authId/token values, cookies, raw bodies or
query strings. It preserves ALDI's full challenge object in memory, fills the
already-validated callback inputs, reuses only a small allowlist of public API
headers from ALDI's own request, and submits exactly one continuation request.
"""

import copy
import json
import time
from urllib.parse import urlsplit

import watcher
from browser_dom import find_visible_elements
from monitoring import navigate, require_origin
from aldi_password_pointer_probe import (
    REPORT_PATH,
    _continuation_url,
    _has_auth_error,
    _prepare_payload,
    _shape,
    utcnow,
)

SAFE_HEADER_NAMES = {
    "accept": "Accept",
    "accept-api-version": "Accept-API-Version",
    "content-type": "Content-Type",
    "x-requested-with": "X-Requested-With",
}


def _safe_request_headers(headers):
    result = {}
    for key, value in (headers or {}).items():
        normalized = str(key).strip().casefold()
        if normalized in SAFE_HEADER_NAMES and isinstance(value, str) and len(value) <= 200:
            result[SAFE_HEADER_NAMES[normalized]] = value
    return result


def _confirmation_meta(challenge):
    result = {"count": 0, "default_index": None, "option_categories": []}
    for callback in challenge.get("callbacks", []) if isinstance(challenge, dict) else []:
        if not isinstance(callback, dict) or callback.get("type") != "ConfirmationCallback":
            continue
        result["count"] += 1
        outputs = {
            item.get("name"): item.get("value")
            for item in callback.get("output", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        options = outputs.get("options")
        default = outputs.get("defaultOption")
        if isinstance(default, int) and not isinstance(default, bool):
            result["default_index"] = default
        if isinstance(options, list):
            for option in options[:10]:
                text = option.casefold() if isinstance(option, str) else ""
                result["option_categories"].append({
                    "login_like": any(word in text for word in ("anmelden", "login", "weiter", "submit", "bestät")),
                    "cancel_like": any(word in text for word in ("abbrechen", "cancel", "zurück", "back")),
                    "passwordless_like": "ohne passwort" in text,
                    "reset_like": any(word in text for word in ("passwort vergessen", "zurücksetzen", "reset")),
                    "empty": not bool(text.strip()),
                })
        break
    return result


def _hidden_meta(challenge):
    rows = []
    for callback in challenge.get("callbacks", []) if isinstance(challenge, dict) else []:
        if not isinstance(callback, dict) or callback.get("type") != "HiddenValueCallback":
            continue
        outputs = {
            item.get("name"): item.get("value")
            for item in callback.get("output", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        identifier = outputs.get("id")
        value = outputs.get("value")
        # Never persist arbitrary values. IDs are reduced to harmless shape only.
        rows.append({
            "id_present": isinstance(identifier, str) and bool(identifier),
            "id_length": len(identifier) if isinstance(identifier, str) else None,
            "value_type": type(value).__name__ if value is not None else "NoneType",
            "value_empty": value in (None, "", [], {}),
        })
    return rows[:30]


def _callback_echo(obj):
    result = {
        "name_secret_echoed": False,
        "password_secret_echoed": False,
        "name_input_present": False,
        "password_input_present": False,
    }
    if not isinstance(obj, dict):
        return result
    for callback in obj.get("callbacks", []):
        if not isinstance(callback, dict):
            continue
        inputs = callback.get("input")
        if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
            continue
        value = inputs[0].get("value")
        if callback.get("type") == "NameCallback":
            result["name_input_present"] = "value" in inputs[0]
            result["name_secret_echoed"] = value == watcher.ALDI_USER
        elif callback.get("type") == "PasswordCallback":
            result["password_input_present"] = "value" in inputs[0]
            result["password_secret_echoed"] = value == watcher.ALDI_PASS
    return result


def _capture_initial(driver, timeout=15):
    deadline = time.monotonic() + timeout
    pending = {}
    while time.monotonic() < deadline:
        try:
            entries = driver.get_log("performance")
        except Exception:
            entries = []
        for entry in entries:
            try:
                message = json.loads(entry.get("message", "{}"))["message"]
                params = message.get("params", {})
                request_id = params.get("requestId")
                if message.get("method") == "Network.requestWillBeSent":
                    request = params.get("request", {})
                    url = request.get("url") or ""
                    parsed = urlsplit(url)
                    if (request.get("method") == "POST"
                            and parsed.scheme == "https"
                            and parsed.hostname == "login.alditalk-kundenbetreuung.de"
                            and parsed.path.rstrip("/").endswith("/authenticate")):
                        pending[request_id] = {
                            "url": url,
                            "headers": _safe_request_headers(request.get("headers", {})),
                            "query_present": bool(parsed.query),
                        }
            except Exception:
                continue

        for request_id, info in list(pending.items()):
            try:
                body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id}).get("body", "")
                obj = json.loads(body)
            except Exception:
                continue
            shape = _shape(obj, 200)
            if (shape.get("stage_identifier") == "stage-loginPage"
                    and shape.get("has_auth_id")
                    and shape.get("has_callbacks")
                    and not shape.get("has_token_id")
                    and not _has_auth_error(shape)):
                return info, obj
        time.sleep(0.35)
    return None, None


def _submit_full_challenge(driver, initial_info, challenge, prepared_callbacks):
    continuation = _continuation_url(initial_info["url"])
    payload = copy.deepcopy(challenge)
    payload["callbacks"] = prepared_callbacks

    headers = dict(initial_info.get("headers") or {})
    headers.setdefault("Accept", "application/json")
    headers.setdefault("Content-Type", "application/json")

    result = driver.execute_async_script(r"""
        const url = arguments[0];
        const payload = arguments[1];
        const headers = arguments[2];
        const done = arguments[arguments.length - 1];
        fetch(url, {
          method: 'POST',
          credentials: 'include',
          cache: 'no-store',
          headers: headers,
          body: JSON.stringify(payload)
        }).then(async response => {
          let body = null;
          try { body = await response.json(); } catch (_) {}
          done({status: response.status, body: body});
        }).catch(() => done({status: 0, body: null}));
    """, continuation, payload, headers)
    if not isinstance(result, dict):
        return 0, None
    return int(result.get("status") or 0), result.get("body")


def main():
    report = {
        "started_at": utcnow(),
        "finished_at": None,
        "outcome": "unknown",
        "booking_executed": False,
        "challenge_shape": None,
        "initial_request": None,
        "confirmation_meta": None,
        "hidden_meta": None,
        "callback_normalization": None,
        "credential_callback_submit_count": 0,
        "credential_response_shape": None,
        "same_auth_id_as_challenge": None,
        "response_callback_echo": None,
        "portal_session": False,
        "exception_type": None,
    }

    if not watcher.configure_credentials("ALDI"):
        report["outcome"] = "credentials_unavailable"
        report["finished_at"] = utcnow()
        with open(REPORT_PATH, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        return 3

    driver = None
    try:
        driver = watcher.build_driver()
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if (find_visible_elements(driver, "input[autocomplete='username'],input[type='tel'],input[type='text']")
                    and find_visible_elements(driver, "input[type='password']")):
                break
            time.sleep(0.25)

        initial_info, challenge = _capture_initial(driver)
        if initial_info is None or challenge is None:
            report["outcome"] = "login_challenge_not_captured"
            return 2

        report["challenge_shape"] = _shape(challenge, 200)
        report["initial_request"] = {
            "query_present": bool(initial_info.get("query_present")),
            "safe_header_names": sorted(initial_info.get("headers", {}).keys()),
            "accept_api_version": initial_info.get("headers", {}).get("Accept-API-Version"),
            "content_type": initial_info.get("headers", {}).get("Content-Type"),
        }
        report["confirmation_meta"] = _confirmation_meta(challenge)
        report["hidden_meta"] = _hidden_meta(challenge)

        prepared, normalization = _prepare_payload(challenge)
        report["callback_normalization"] = normalization
        report["credential_callback_submit_count"] = 1
        status, response_obj = _submit_full_challenge(
            driver, initial_info, challenge, prepared["callbacks"]
        )
        report["credential_response_shape"] = _shape(response_obj, status)
        report["response_callback_echo"] = _callback_echo(response_obj)
        if isinstance(response_obj, dict) and isinstance(response_obj.get("authId"), str):
            report["same_auth_id_as_challenge"] = response_obj.get("authId") == challenge.get("authId")

        if status != 200:
            report["outcome"] = "credential_callback_http_error"
            return 2
        if _has_auth_error(report["credential_response_shape"]):
            report["outcome"] = "credential_callback_rejected_or_error"
            return 2
        if report["credential_response_shape"].get("has_token_id"):
            navigate(driver, watcher.ALDI_OVERVIEW_URL, attempts=1)
            require_origin(driver, watcher.ALDI_OVERVIEW_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
            session_deadline = time.monotonic() + 15
            while time.monotonic() < session_deadline:
                if watcher.aldi_session_visible(driver):
                    report["portal_session"] = True
                    report["outcome"] = "portal_session_confirmed"
                    return 0
                time.sleep(0.5)
            report["outcome"] = "token_observed_session_not_confirmed"
            return 5

        if report["credential_response_shape"].get("has_callbacks"):
            if report["same_auth_id_as_challenge"] is False:
                report["outcome"] = "auth_tree_restarted"
            elif report["same_auth_id_as_challenge"] is True:
                report["outcome"] = "same_auth_tree_same_stage"
            else:
                report["outcome"] = "callback_stage_returned"
            return 6

        report["outcome"] = "credential_callback_unrecognized_response"
        return 2
    except Exception as exc:
        report["outcome"] = "exception"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        report["finished_at"] = utcnow()
        with open(REPORT_PATH, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({
            "outcome": report["outcome"],
            "initial_request": report["initial_request"],
            "confirmation_meta": report["confirmation_meta"],
            "callback_normalization": report["callback_normalization"],
            "credential_callback_submit_count": report["credential_callback_submit_count"],
            "credential_response_shape": report["credential_response_shape"],
            "same_auth_id_as_challenge": report["same_auth_id_as_challenge"],
            "response_callback_echo": report["response_callback_echo"],
            "portal_session": report["portal_session"],
            "exception_type": report["exception_type"],
            "booking_executed": False,
        }, ensure_ascii=False), flush=True)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
