"""Compare ALDI's initial auth request with one sanitized continuation POST.

This diagnostic never logs secrets, authId/token values, cookies, raw bodies or
query strings. It preserves ALDI's full challenge object in memory, fills the
already-validated callback inputs, reuses only a small allowlist of public API
headers from ALDI's own request, and submits exactly one continuation request.
"""

import copy
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import watcher
from browser_dom import find_visible_elements
from monitoring import navigate, require_origin
from aldi_sso_diagnostic import _classify_text

REPORT_PATH = os.getenv("ALDI_PASSWORD_POINTER_REPORT", "aldi-password-pointer.json")
ALLOWED_AUTH_HOSTS = {"login.alditalk-kundenbetreuung.de"}
SAFE_HEADER_NAMES = {
    "accept": "Accept",
    "accept-api-version": "Accept-API-Version",
    "content-type": "Content-Type",
    "x-requested-with": "X-Requested-With",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _callback_schema(obj):
    rows = []
    for callback in obj.get("callbacks", []) if isinstance(obj, dict) else []:
        if not isinstance(callback, dict):
            continue
        rows.append({
            "type": str(callback.get("type") or "")[:80],
            "input_names": [
                str(item.get("name") or "")[:80]
                for item in callback.get("input", [])
                if isinstance(item, dict)
            ][:12],
            "output_names": [
                str(item.get("name") or "")[:80]
                for item in callback.get("output", [])
                if isinstance(item, dict)
            ][:20],
        })
    return rows[:30]


def _text_output_category(obj):
    parts = []
    if isinstance(obj, dict):
        for callback in obj.get("callbacks", []):
            if not isinstance(callback, dict) or callback.get("type") != "TextOutputCallback":
                continue
            for item in callback.get("output", []):
                if isinstance(item, dict) and isinstance(item.get("value"), str):
                    parts.append(item["value"])
    return _classify_text(" ".join(parts))


def _shape(obj, status=None):
    return {
        "http_status": status,
        "json_object": isinstance(obj, dict),
        "top_keys": sorted(str(k)[:64] for k in obj.keys())[:30] if isinstance(obj, dict) else [],
        "stage_identifier": (
            obj.get("stage") if isinstance(obj, dict)
            and isinstance(obj.get("stage"), str)
            and len(obj.get("stage")) <= 80 else None
        ),
        "has_auth_id": isinstance(obj, dict) and isinstance(obj.get("authId"), str) and bool(obj.get("authId")),
        "has_token_id": isinstance(obj, dict) and isinstance(obj.get("tokenId"), str) and bool(obj.get("tokenId")),
        "has_callbacks": isinstance(obj, dict) and isinstance(obj.get("callbacks"), list),
        "callback_schema": _callback_schema(obj),
        "text_output_category": _text_output_category(obj),
        "has_success_url": isinstance(obj, dict) and isinstance(obj.get("successUrl"), str),
        "has_failure_url": isinstance(obj, dict) and isinstance(obj.get("failureUrl"), str),
    }


def _has_auth_error(shape):
    category = (shape or {}).get("text_output_category") or {}
    return any(category.get(key) for key in (
        "invalid_credentials", "account_locked", "account_deactivated",
        "technical_error", "required_fields", "session_error", "unknown_error_text",
    ))


def _validated_auth_url(url):
    try:
        parsed = urlsplit(url or "")
        return (parsed.scheme == "https"
                and parsed.hostname in ALLOWED_AUTH_HOSTS
                and parsed.path.rstrip("/").endswith("/authenticate"))
    except Exception:
        return False


def _continuation_url(exact_url):
    if not _validated_auth_url(exact_url):
        raise PermissionError("untrusted_auth_url")
    parsed = urlsplit(exact_url)
    continuation = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if not _validated_auth_url(continuation):
        raise PermissionError("untrusted_continuation_url")
    return continuation


def _single_input(callback):
    inputs = callback.get("input")
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
        raise RuntimeError("unexpected_callback_input_shape")
    name = inputs[0].get("name")
    if not isinstance(name, str) or not name or len(name) > 80:
        raise RuntimeError("unexpected_callback_input_name")
    return inputs[0]


def _output_value(callback, name):
    matches = [
        item.get("value")
        for item in callback.get("output", [])
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise RuntimeError("expected_callback_output_missing")
    return matches[0]


def _confirmation_index(callback):
    options = _output_value(callback, "options")
    default = _output_value(callback, "defaultOption")
    if not isinstance(options, list) or not options or len(options) > 10:
        raise RuntimeError("confirmation_options_unexpected")
    if (isinstance(default, int) and not isinstance(default, bool)
            and 0 <= default < len(options)):
        return default, "aldi_default_option"
    candidates = []
    for index, option in enumerate(options):
        if not isinstance(option, str):
            continue
        normalized = option.strip().casefold()
        if re.search(r"\b(?:anmelden|login|submit|weiter|bestätigen|bestaetigen)\b", normalized):
            candidates.append(index)
    if len(candidates) == 1:
        return candidates[0], "unique_login_option"
    raise RuntimeError("confirmation_choice_ambiguous")


def _prepare_payload(challenge):
    if not isinstance(challenge, dict) or not isinstance(challenge.get("authId"), str):
        raise RuntimeError("challenge_missing_auth_id")
    callbacks = challenge.get("callbacks")
    if not isinstance(callbacks, list):
        raise RuntimeError("challenge_missing_callbacks")
    allowed = {
        "NameCallback", "PasswordCallback", "ConfirmationCallback",
        "HiddenValueCallback", "TextOutputCallback",
    }
    counts = {"NameCallback": 0, "PasswordCallback": 0, "ConfirmationCallback": 0}
    normalization = {
        "hidden_callbacks": 0,
        "hidden_values_copied_from_aldi_output": 0,
        "confirmation_set": False,
        "confirmation_selection_basis": None,
        "continuation_query_stripped": True,
        "full_challenge_object_sent": True,
    }
    payload_callbacks = copy.deepcopy(callbacks)
    for callback in payload_callbacks:
        if not isinstance(callback, dict):
            raise RuntimeError("unexpected_callback_shape")
        kind = callback.get("type")
        if kind not in allowed:
            raise RuntimeError("unexpected_callback_type")
        if kind == "NameCallback":
            counts[kind] += 1
            _single_input(callback)["value"] = watcher.ALDI_USER
        elif kind == "PasswordCallback":
            counts[kind] += 1
            _single_input(callback)["value"] = watcher.ALDI_PASS
        elif kind == "HiddenValueCallback":
            normalization["hidden_callbacks"] += 1
            _single_input(callback)["value"] = _output_value(callback, "value")
            normalization["hidden_values_copied_from_aldi_output"] += 1
        elif kind == "ConfirmationCallback":
            counts[kind] += 1
            index, basis = _confirmation_index(callback)
            _single_input(callback)["value"] = index
            normalization["confirmation_set"] = True
            normalization["confirmation_selection_basis"] = basis
    if counts != {"NameCallback": 1, "PasswordCallback": 1, "ConfirmationCallback": 1}:
        raise RuntimeError("required_callback_count_unexpected")
    return payload_callbacks, normalization


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
                            and parsed.hostname in ALLOWED_AUTH_HOSTS
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

        prepared_callbacks, normalization = _prepare_payload(challenge)
        report["callback_normalization"] = normalization
        report["credential_callback_submit_count"] = 1
        status, response_obj = _submit_full_challenge(
            driver, initial_info, challenge, prepared_callbacks
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
