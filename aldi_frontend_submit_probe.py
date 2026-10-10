"""Observe one real ALDI frontend credential submit without logging secrets.

The probe waits for ALDI's initial stage-loginPage challenge, fills the rendered
username/password components, then activates the unique enabled password-login
control with one trusted Chrome pointer click. It records only sanitized request
and response structure: whether the real frontend included the configured
secrets, callback selection, continuation URL shape, and whether hidden inputs
match ALDI's challenge. Raw request/response bodies, authId, token, cookies and
credential values are never persisted or printed. No booking control is touched.
"""

import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

import watcher
from browser_dom import element_label, find_visible_elements
from monitoring import navigate, require_origin
from aldi_callback_fidelity_probe import _capture_initial, _shape

REPORT_PATH = os.getenv("ALDI_PASSWORD_POINTER_REPORT", "aldi-password-pointer.json")
ALLOWED_AUTH_HOST = "login.alditalk-kundenbetreuung.de"


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _valid_auth_url(url):
    try:
        parsed = urlsplit(url or "")
        return (parsed.scheme == "https"
                and parsed.hostname == ALLOWED_AUTH_HOST
                and parsed.path.rstrip("/").endswith("/authenticate"))
    except Exception:
        return False


def _unique_enabled(driver, selector):
    require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
    items = find_visible_elements(driver, selector)
    enabled = []
    for item in items:
        try:
            if (item.is_enabled()
                    and item.get_attribute("aria-disabled") != "true"
                    and item.get_attribute("disabled") is None):
                enabled.append(item)
        except Exception:
            continue
    return enabled[0] if len(enabled) == 1 else False


def _login_control(driver):
    matches = []
    for element in find_visible_elements(driver, "button,a,[role='button'],input[type='submit']"):
        try:
            if (element_label(driver, element).strip().casefold() == "anmelden"
                    and element.is_enabled()
                    and element.get_attribute("aria-disabled") != "true"
                    and element.get_attribute("disabled") is None):
                matches.append(element)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else False


def _fill_field(field, value):
    field.send_keys(Keys.CONTROL, "a")
    field.send_keys(Keys.BACKSPACE)
    field.send_keys(value)
    field.send_keys(Keys.TAB)


def _trusted_pointer_click(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'center'});", element)
    time.sleep(0.25)
    rect = driver.execute_script(
        "const r=arguments[0].getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height};",
        element,
    )
    if not rect or rect.get("w", 0) <= 1 or rect.get("h", 0) <= 1:
        raise RuntimeError("login_control_not_rendered")
    x = float(rect["x"]) + float(rect["w"]) / 2.0
    y = float(rect["y"]) + float(rect["h"]) / 2.0
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": x, "y": y, "button": "none"
    })
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1
    })
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1
    })


def _single_callback_input(callback):
    inputs = callback.get("input") if isinstance(callback, dict) else None
    if isinstance(inputs, list) and len(inputs) == 1 and isinstance(inputs[0], dict):
        return inputs[0]
    return None


def _challenge_hidden_map(challenge):
    result = {}
    for callback in challenge.get("callbacks", []) if isinstance(challenge, dict) else []:
        if not isinstance(callback, dict) or callback.get("type") != "HiddenValueCallback":
            continue
        input_item = _single_callback_input(callback)
        if input_item and isinstance(input_item.get("name"), str):
            result[input_item["name"]] = input_item.get("value")
    return result


def _request_shape(payload, challenge):
    shape = {
        "json_object": isinstance(payload, dict),
        "top_keys": sorted(str(key)[:64] for key in payload.keys())[:30] if isinstance(payload, dict) else [],
        "has_auth_id": isinstance(payload, dict) and isinstance(payload.get("authId"), str) and bool(payload.get("authId")),
        "same_auth_id_as_challenge": None,
        "callback_types": [],
        "name_callback_count": 0,
        "password_callback_count": 0,
        "confirmation_callback_count": 0,
        "hidden_callback_count": 0,
        "username_secret_present": False,
        "password_secret_present": False,
        "confirmation_value": None,
        "hidden_inputs_match_challenge": None,
        "full_challenge_top_keys_preserved": None,
    }
    if not isinstance(payload, dict):
        return shape

    if isinstance(challenge, dict) and isinstance(challenge.get("authId"), str):
        shape["same_auth_id_as_challenge"] = payload.get("authId") == challenge.get("authId")
        shape["full_challenge_top_keys_preserved"] = set(challenge.keys()).issubset(set(payload.keys()))

    expected_hidden = _challenge_hidden_map(challenge)
    observed_hidden = {}
    callbacks = payload.get("callbacks")
    if not isinstance(callbacks, list):
        return shape

    for callback in callbacks:
        if not isinstance(callback, dict):
            continue
        kind = str(callback.get("type") or "")[:80]
        shape["callback_types"].append(kind)
        input_item = _single_callback_input(callback)
        value = input_item.get("value") if input_item else None
        if kind == "NameCallback":
            shape["name_callback_count"] += 1
            shape["username_secret_present"] = value == watcher.ALDI_USER
        elif kind == "PasswordCallback":
            shape["password_callback_count"] += 1
            shape["password_secret_present"] = value == watcher.ALDI_PASS
        elif kind == "ConfirmationCallback":
            shape["confirmation_callback_count"] += 1
            if isinstance(value, int) and not isinstance(value, bool):
                shape["confirmation_value"] = value
        elif kind == "HiddenValueCallback":
            shape["hidden_callback_count"] += 1
            if input_item and isinstance(input_item.get("name"), str):
                observed_hidden[input_item["name"]] = value

    if expected_hidden:
        shape["hidden_inputs_match_challenge"] = observed_hidden == expected_hidden
    return shape


def _safe_headers(headers):
    names = []
    api_version = None
    for key, value in (headers or {}).items():
        normalized = str(key).casefold()
        if normalized in {"accept", "accept-api-version", "content-type", "x-requested-with"}:
            names.append(str(key)[:64])
        if normalized == "accept-api-version" and isinstance(value, str) and len(value) <= 200:
            api_version = value
    return sorted(names), api_version


def _capture_frontend_submit(driver, challenge, timeout=12):
    deadline = time.monotonic() + timeout
    request_rows = []
    responses = {}
    seen_request_ids = set()

    while time.monotonic() < deadline:
        try:
            entries = driver.get_log("performance")
        except Exception:
            entries = []
        for entry in entries:
            try:
                message = json.loads(entry.get("message", "{}"))["message"]
                method = message.get("method")
                params = message.get("params", {})
                request_id = params.get("requestId")
                if method == "Network.requestWillBeSent":
                    request = params.get("request", {})
                    url = request.get("url") or ""
                    if (request.get("method") != "POST" or not _valid_auth_url(url)
                            or request_id in seen_request_ids):
                        continue
                    seen_request_ids.add(request_id)
                    post_data = None
                    try:
                        post_data = driver.execute_cdp_cmd(
                            "Network.getRequestPostData", {"requestId": request_id}
                        ).get("postData")
                    except Exception:
                        raw = request.get("postData")
                        if isinstance(raw, str):
                            post_data = raw
                    payload = None
                    if isinstance(post_data, str):
                        try:
                            payload = json.loads(post_data)
                        except Exception:
                            payload = None
                    parsed = urlsplit(url)
                    header_names, api_version = _safe_headers(request.get("headers", {}))
                    request_rows.append({
                        "request_id": request_id,
                        "url_query_present": bool(parsed.query),
                        "safe_header_names": header_names,
                        "accept_api_version": api_version,
                        "post_data_present": isinstance(post_data, str) and bool(post_data),
                        "payload_shape": _request_shape(payload, challenge),
                    })
                elif method == "Network.responseReceived":
                    response = params.get("response", {})
                    url = response.get("url") or ""
                    if request_id in seen_request_ids and _valid_auth_url(url):
                        responses[request_id] = int(response.get("status") or 0)
            except Exception:
                continue

        if request_rows:
            row = request_rows[-1]
            request_id = row.pop("request_id")
            status = responses.get(request_id)
            response_obj = None
            if status is not None:
                try:
                    raw_body = driver.execute_cdp_cmd(
                        "Network.getResponseBody", {"requestId": request_id}
                    ).get("body", "")
                    response_obj = json.loads(raw_body)
                except Exception:
                    response_obj = None
            row["response_shape"] = _shape(response_obj, status) if status is not None else None
            return row
        time.sleep(0.35)
    return None


def main():
    report = {
        "started_at": utcnow(),
        "finished_at": None,
        "outcome": "unknown",
        "booking_executed": False,
        "challenge_captured": False,
        "credential_fields_match": None,
        "frontend_submit_count": 0,
        "frontend_request": None,
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

        initial_info, challenge = _capture_initial(driver, timeout=20)
        if initial_info is None or challenge is None:
            report["outcome"] = "login_challenge_not_captured"
            return 2
        report["challenge_captured"] = True

        wait = WebDriverWait(driver, 20)
        user = wait.until(lambda _: _unique_enabled(
            driver, "input[autocomplete='username'],input[type='tel'],input[type='text']"
        ))
        password = wait.until(lambda _: _unique_enabled(driver, "input[type='password']"))
        _fill_field(user, watcher.ALDI_USER)
        password = wait.until(lambda _: _unique_enabled(driver, "input[type='password']"))
        _fill_field(password, watcher.ALDI_PASS)

        # Re-resolve after blur/component updates before checking values.
        user = wait.until(lambda _: _unique_enabled(
            driver, "input[autocomplete='username'],input[type='tel'],input[type='text']"
        ))
        password = wait.until(lambda _: _unique_enabled(driver, "input[type='password']"))
        submit = wait.until(lambda _: _login_control(driver))
        report["credential_fields_match"] = {
            "username": user.get_attribute("value") == watcher.ALDI_USER,
            "password": password.get_attribute("value") == watcher.ALDI_PASS,
            "submit_enabled": bool(submit),
        }
        if not all(report["credential_fields_match"].values()):
            report["outcome"] = "rendered_form_not_ready"
            return 4

        # Clear all already-consumed navigation/auth-tree logs. Exactly one
        # trusted UI submit follows, and only its new network request is observed.
        try:
            driver.get_log("performance")
        except Exception:
            pass
        _trusted_pointer_click(driver, submit)
        report["frontend_submit_count"] = 1

        request_row = _capture_frontend_submit(driver, challenge)
        report["frontend_request"] = request_row
        if request_row is None:
            report["outcome"] = "frontend_click_no_new_auth_request"
            return 2

        response_shape = request_row.get("response_shape") or {}
        if response_shape.get("has_token_id"):
            navigate(driver, watcher.ALDI_OVERVIEW_URL, attempts=1)
            require_origin(driver, watcher.ALDI_OVERVIEW_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if watcher.aldi_session_visible(driver):
                    report["portal_session"] = True
                    report["outcome"] = "portal_session_confirmed"
                    return 0
                time.sleep(0.5)
            report["outcome"] = "frontend_token_session_not_confirmed"
            return 5

        payload_shape = request_row.get("payload_shape") or {}
        if (payload_shape.get("username_secret_present")
                and payload_shape.get("password_secret_present")):
            report["outcome"] = "frontend_credentials_submitted_no_token"
            return 6
        report["outcome"] = "frontend_request_missing_credentials"
        return 2
    except Exception as exc:
        report["outcome"] = "exception"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        report["finished_at"] = utcnow()
        with open(REPORT_PATH, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
