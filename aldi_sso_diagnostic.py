"""Sanitized ALDI SSO diagnostic.

Exactly one login submission is performed. No refill control is activated.
The report stores structure/booleans only: never credentials, field values,
cookie values, query strings, tokens, or raw response bodies.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import unquote_plus, urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from browser_dom import element_label, find_visible_elements, rendered_text
from monitoring import navigate, require_origin
import watcher


OBSERVE_SECONDS = int(os.getenv("ALDI_SSO_OBSERVE_SECONDS", "45"))
SAMPLE_SECONDS = max(2, int(os.getenv("ALDI_SSO_SAMPLE_SECONDS", "3")))
PROBE_AFTER_SECONDS = max(5, int(os.getenv("ALDI_SSO_PROBE_AFTER_SECONDS", "15")))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def safe_url(url):
    try:
        parsed = urlsplit(url or "")
        path = parsed.path or "/"
        clean = []
        for part in path.split("/"):
            if len(part) > 40 or re.fullmatch(r"[A-Fa-f0-9]{24,}", part or "") or re.fullmatch(r"[A-Za-z0-9_-]{48,}", part or ""):
                clean.append(":opaque")
            else:
                clean.append(part[:80])
        return {"scheme": parsed.scheme, "host": parsed.hostname, "path": "/".join(clean) or "/"}
    except Exception:
        return {"scheme": None, "host": None, "path": None}


def _count(driver, selector):
    try:
        return len(find_visible_elements(driver, selector))
    except Exception:
        return None


def _alert_category(driver):
    result = {
        "invalid_credentials": False,
        "account_locked": False,
        "technical_error": False,
        "required_fields": False,
        "session_error": False,
        "unknown_alert": False,
    }
    pieces = []
    try:
        for element in find_visible_elements(driver, "[role='alert'],[aria-live='assertive'],[aria-live='polite']")[:8]:
            text = rendered_text(driver, element).strip().casefold()
            if text:
                pieces.append(text)
    except Exception:
        return result
    text = " ".join(pieces)
    if not text:
        return result
    result["invalid_credentials"] = any(x in text for x in (
        "rufnummer oder passwort", "benutzername oder passwort", "passwort falsch",
        "anmeldedaten", "zugangsdaten", "nicht korrekt", "nicht erkannt",
    ))
    result["account_locked"] = any(x in text for x in ("gesperrt", "zu viele versuche"))
    result["technical_error"] = any(x in text for x in (
        "technischer fehler", "technische störung", "technische stoerung",
        "später erneut", "spaeter erneut", "momentan nicht verfügbar", "momentan nicht verfuegbar",
    ))
    result["required_fields"] = any(x in text for x in ("pflichtfeld", "erforderlich", "ausfüllen", "ausfuellen"))
    result["session_error"] = "session" in text and any(x in text for x in ("abgelaufen", "ungültig", "ungueltig"))
    result["unknown_alert"] = not any(result.values())
    return result


def snapshot(driver, elapsed):
    try:
        text = rendered_text(driver).casefold()
    except Exception:
        text = ""
    return {
        "elapsed_s": round(elapsed, 1),
        "url": safe_url(getattr(driver, "current_url", "")),
        "username_fields": _count(driver, "input[autocomplete='username'],input[type='tel'],input[type='text']"),
        "password_fields": _count(driver, "input[type='password']"),
        "alerts": _count(driver, "[role='alert'],[aria-live='assertive'],[aria-live='polite']"),
        "login_controls": sum(
            1 for e in (find_visible_elements(driver, "button,a,[role='button'],input[type='submit']") if driver else [])
            if element_label(driver, e).strip().casefold() in {"anmelden", "einloggen", "login"}
        ),
        "error_text": any(x in text for x in ("fehler", "fehlgeschlagen", "ungültig", "ungueltig", "nicht möglich", "nicht moeglich")),
        "captcha_text": any(x in text for x in ("captcha", "ich bin kein roboter")),
        "mfa_text": any(x in text for x in ("zwei-faktor", "2fa", "sicherheitscode", "verifizierung")),
        "alert_category": _alert_category(driver),
    }


def _secret_present(post_data, secret):
    if not secret or not post_data:
        return False
    try:
        obj = json.loads(post_data)
        stack = [obj]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, str) and item == secret:
                return True
    except Exception:
        pass
    try:
        return secret in post_data or secret in unquote_plus(post_data)
    except Exception:
        return False


def _response_shape(driver, request_id, status):
    shape = {
        "status": status,
        "body_available": False,
        "json_object": False,
        "top_keys": [],
        "has_auth_id": False,
        "has_token_id": False,
        "has_callbacks": False,
        "callback_types": [],
        "has_success_url": False,
        "has_failure_url": False,
        "has_stage": False,
        "has_message": False,
    }
    try:
        body_info = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
        body = body_info.get("body", "")
        obj = json.loads(body)
        shape["body_available"] = True
        shape["json_object"] = isinstance(obj, dict)
        if not isinstance(obj, dict):
            return shape
        shape["top_keys"] = sorted(str(k)[:64] for k in obj.keys())[:40]
        shape["has_auth_id"] = "authId" in obj
        shape["has_token_id"] = "tokenId" in obj
        shape["has_callbacks"] = isinstance(obj.get("callbacks"), list)
        shape["has_success_url"] = "successUrl" in obj
        shape["has_failure_url"] = "failureUrl" in obj
        shape["has_stage"] = "stage" in obj
        shape["has_message"] = "message" in obj
        if isinstance(obj.get("callbacks"), list):
            types = {
                str(cb.get("type"))[:80]
                for cb in obj["callbacks"]
                if isinstance(cb, dict) and cb.get("type")
            }
            shape["callback_types"] = sorted(types)[:30]
    except Exception:
        pass
    return shape


def drain_network(driver, report, seen):
    allowed_suffixes = ("alditalk-kundenportal.de", "alditalk-kundenbetreuung.de", "alditalk.de")
    try:
        logs = driver.get_log("performance")
    except Exception:
        return
    for item in logs:
        try:
            msg = json.loads(item.get("message", "{}"))["message"]
            method = msg.get("method")
            params = msg.get("params", {})
            if method == "Network.requestWillBeSent":
                req = params.get("request", {})
                safe = safe_url(req.get("url"))
                host = safe.get("host") or ""
                if not host.endswith(allowed_suffixes):
                    continue
                key = ("q", req.get("method"), host, safe.get("path"))
                if key not in seen:
                    seen.add(key)
                    report["network"].append({"event": "request", "method": req.get("method"), "url": safe, "resource_type": params.get("type")})
                if safe.get("path", "").endswith("/authenticate") and req.get("method") == "POST":
                    post_data = req.get("postData", "")
                    report["auth_request_shape"] = {
                        "post_data_present": bool(post_data),
                        "username_secret_present": _secret_present(post_data, watcher.ALDI_USER),
                        "password_secret_present": _secret_present(post_data, watcher.ALDI_PASS),
                    }
            elif method == "Network.responseReceived":
                resp = params.get("response", {})
                safe = safe_url(resp.get("url"))
                host = safe.get("host") or ""
                if not host.endswith(allowed_suffixes):
                    continue
                status = resp.get("status")
                key = ("r", status, host, safe.get("path"))
                if key not in seen:
                    seen.add(key)
                    report["network"].append({"event": "response", "status": status, "url": safe, "resource_type": params.get("type")})
                if safe.get("path", "").endswith("/authenticate"):
                    report["auth_response_shapes"].append(_response_shape(driver, params.get("requestId"), status))
        except Exception:
            continue
    report["network"] = report["network"][-120:]
    report["auth_response_shapes"] = report["auth_response_shapes"][-12:]


def main():
    report_path = os.getenv("ALDI_SSO_REPORT", "aldi-sso-diagnostic.json")
    report = {
        "started_at": utcnow(),
        "finished_at": None,
        "booking_executed": False,
        "login_submit_count": 0,
        "submit_method": "validated_login_control_enter",
        "credential_field_state": None,
        "auth_request_shape": None,
        "auth_response_shapes": [],
        "protected_probe_count": 0,
        "outcome": "unknown",
        "samples": [],
        "network": [],
        "exception_type": None,
    }
    if not watcher.configure_credentials("ALDI"):
        report["outcome"] = "credentials_unavailable"
        report["finished_at"] = utcnow()
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        return 3

    driver = None
    seen = set()
    try:
        driver = watcher.build_driver()
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)
        wait = WebDriverWait(driver, 30)

        def unique_enabled(selector):
            require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
            items = find_visible_elements(driver, selector)
            return items[0] if len(items) == 1 and items[0].is_enabled() else False

        user = wait.until(lambda _: unique_enabled("input[autocomplete='username'],input[type='tel'],input[type='text']"))
        user.send_keys(Keys.CONTROL, "a")
        user.send_keys(Keys.BACKSPACE)
        user.send_keys(watcher.ALDI_USER)
        user.send_keys(Keys.TAB)

        password = wait.until(lambda _: unique_enabled("input[type='password']"))
        password.send_keys(Keys.CONTROL, "a")
        password.send_keys(Keys.BACKSPACE)
        password.send_keys(watcher.ALDI_PASS)
        password.send_keys(Keys.TAB)

        def trusted_submit(_):
            controls = [
                e for e in find_visible_elements(driver, "button,a,[role='button'],input[type='submit']")
                if element_label(driver, e).strip().casefold() == "anmelden"
                and e.is_enabled() and e.get_attribute("aria-disabled") != "true"
            ]
            return controls[0] if len(controls) == 1 else False

        submit = wait.until(trusted_submit)
        user = wait.until(lambda _: unique_enabled("input[autocomplete='username'],input[type='tel'],input[type='text']"))
        password = wait.until(lambda _: unique_enabled("input[type='password']"))
        report["credential_field_state"] = {
            "username_matches_secret": user.get_attribute("value") == watcher.ALDI_USER,
            "password_matches_secret": password.get_attribute("value") == watcher.ALDI_PASS,
            "submit_enabled": bool(submit.is_enabled()) and submit.get_attribute("aria-disabled") != "true",
        }

        submit.send_keys(Keys.ENTER)
        report["login_submit_count"] = 1
        start = time.monotonic()
        protected_probe_done = False

        while True:
            elapsed = time.monotonic() - start
            drain_network(driver, report, seen)
            report["samples"].append(snapshot(driver, elapsed))
            if watcher.aldi_session_visible(driver):
                report["outcome"] = "portal_session_confirmed"
                break
            if not protected_probe_done and elapsed >= PROBE_AFTER_SECONDS:
                protected_probe_done = True
                report["protected_probe_count"] = 1
                navigate(driver, watcher.ALDI_OVERVIEW_URL, attempts=1)
                drain_network(driver, report, seen)
                if watcher.aldi_session_visible(driver):
                    report["outcome"] = "portal_session_confirmed"
                    break
            if elapsed >= OBSERVE_SECONDS:
                report["outcome"] = "sso_timeout"
                break
            time.sleep(SAMPLE_SECONDS)
        drain_network(driver, report, seen)
    except Exception as exc:
        report["outcome"] = "exception"
        report["exception_type"] = type(exc).__name__
        if driver is not None:
            drain_network(driver, report, seen)
    finally:
        report["finished_at"] = utcnow()
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        latest = report["samples"][-1] if report["samples"] else {}
        print(json.dumps({
            "outcome": report["outcome"],
            "credential_field_state": report["credential_field_state"],
            "auth_request_shape": report["auth_request_shape"],
            "auth_response_shapes": report["auth_response_shapes"],
            "last_alert_category": latest.get("alert_category", {}),
            "booking_executed": False,
        }, ensure_ascii=False), flush=True)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
    return 0 if report["outcome"] == "portal_session_confirmed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
