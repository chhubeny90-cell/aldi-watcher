"""Sanitized ALDI authentication probe for GitHub Actions.

The probe performs the same account login as watcher.py but never books or
clicks a refill control. On authentication failure it emits only structural,
allowlisted booleans/counts so SSO/MFA/error states can be distinguished
without exposing account data, page text, URLs, cookies, tokens, or raw errors.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from selenium.common.exceptions import TimeoutException, WebDriverException

import watcher
from browser_dom import element_label, find_visible_elements
from monitoring import safe_refill_evidence, utcnow, write_report


REPORT = Path("monitoring-report.json")
_ALLOWED_WEBDRIVER_ERRORS = {
    'ElementClickInterceptedException',
    'ElementNotInteractableException',
    'StaleElementReferenceException',
    'JavascriptException',
    'InvalidElementStateException',
    'NoSuchElementException',
    'TimeoutException',
    'WebDriverException',
}


def _visible(elements):
    result = []
    for element in elements:
        try:
            if element.is_displayed():
                result.append(element)
        except Exception:
            continue
    return result


def _url_parts(driver):
    try:
        return urlsplit(driver.current_url)
    except Exception:
        return None


def _host_class(driver):
    parsed = _url_parts(driver)
    if parsed is None:
        return "unknown"
    if parsed.hostname == "login.alditalk-kundenbetreuung.de":
        return "aldi_sso"
    if parsed.hostname == "www.alditalk-kundenportal.de":
        return "aldi_portal"
    return "other"


def _path_class(driver):
    """Classify the current route without persisting the route or its query."""
    parsed = _url_parts(driver)
    if parsed is None:
        return "unknown"
    path = (parsed.path or "/").casefold()
    if path.startswith("/signin/xui"):
        return "signin_ui"
    if "authorize" in path or "oauth" in path:
        return "authorization_flow"
    if "callback" in path or "redirect" in path:
        return "callback_like"
    if path in {"", "/"}:
        return "root"
    return "other"


def _network_state(driver):
    """Return bounded network classifications only; never URLs, headers or bodies."""
    counts = {
        "network_401_count": 0,
        "network_401_document_count": 0,
        "network_401_fetch_xhr_count": 0,
        "network_401_get_count": 0,
        "network_401_post_count": 0,
        "network_401_sso_count": 0,
        "network_401_portal_count": 0,
        "network_401_other_count": 0,
        "network_403_count": 0,
        "network_404_count": 0,
        "network_429_count": 0,
        "network_5xx_count": 0,
        "network_failed_count": 0,
        "redirect_count": 0,
    }
    methods = {}
    try:
        for entry in driver.get_log("performance"):
            message = json.loads(entry["message"])["message"]
            params = message.get("params", {})
            event = message.get("method")
            request_id = params.get("requestId")
            if event == "Network.requestWillBeSent":
                request = params.get("request", {})
                if request_id:
                    methods[request_id] = str(request.get("method", "")).upper()
                if "redirectResponse" in params:
                    counts["redirect_count"] += 1
                continue
            if event == "Network.loadingFailed":
                counts["network_failed_count"] += 1
                continue
            if event != "Network.responseReceived":
                continue
            response = params.get("response", {})
            status = int(response.get("status", 0) or 0)
            if status == 401:
                counts["network_401_count"] += 1
                resource_type = str(params.get("type", ""))
                if resource_type == "Document":
                    counts["network_401_document_count"] += 1
                elif resource_type in {"Fetch", "XHR"}:
                    counts["network_401_fetch_xhr_count"] += 1
                request_method = methods.get(request_id, "")
                if request_method == "GET":
                    counts["network_401_get_count"] += 1
                elif request_method == "POST":
                    counts["network_401_post_count"] += 1
                try:
                    host = urlsplit(response.get("url", "")).hostname
                except Exception:
                    host = None
                if host == "login.alditalk-kundenbetreuung.de":
                    counts["network_401_sso_count"] += 1
                elif host == "www.alditalk-kundenportal.de":
                    counts["network_401_portal_count"] += 1
                else:
                    counts["network_401_other_count"] += 1
            elif status == 403:
                counts["network_403_count"] += 1
            elif status == 404:
                counts["network_404_count"] += 1
            elif status == 429:
                counts["network_429_count"] += 1
            elif 500 <= status <= 599:
                counts["network_5xx_count"] += 1
    except Exception:
        pass
    return counts


def _structural_state(driver):
    """Return only non-secret structural indicators from the current page."""
    state = {
        "host_class": _host_class(driver),
        "path_class": _path_class(driver),
        "cookie_count": None,
        "visible_input_count": None,
        "visible_password_count": None,
        "mfa_input_visible": False,
        "alert_region_visible": False,
        "invalid_input_count": None,
        "visible_control_count": None,
        "login_submit_visible": False,
        "login_submit_enabled": False,
        "continue_control_visible": False,
        "consent_control_visible": False,
        "logout_visible": False,
        "frame_count": None,
        "document_ready": None,
    }
    try:
        state["cookie_count"] = len(driver.get_cookies())
    except Exception:
        pass
    try:
        inputs = _visible(find_visible_elements(driver, "input"))
        state["visible_input_count"] = len(inputs)
        state["visible_password_count"] = sum(
            (element.get_attribute("type") or "").lower() == "password"
            for element in inputs
        )
        state["mfa_input_visible"] = any(
            (element.get_attribute("autocomplete") or "").lower() == "one-time-code"
            for element in inputs
        )
        state["invalid_input_count"] = sum(
            (element.get_attribute("aria-invalid") or "").lower() == "true"
            for element in inputs
        )
    except Exception:
        pass
    try:
        alerts = _visible(find_visible_elements(
            driver, "[role='alert'],[aria-live='assertive'],[aria-live='polite']"
        ))
        state["alert_region_visible"] = bool(alerts)
    except Exception:
        pass
    try:
        controls = _visible(find_visible_elements(
            driver, "button,a,[role='button'],input[type='submit']"
        ))
        state["visible_control_count"] = len(controls)
        labels = [element_label(driver, element).strip().casefold() for element in controls]
        submits = [element for element, label in zip(controls, labels) if label == "anmelden"]
        state["login_submit_visible"] = len(submits) == 1
        if len(submits) == 1:
            state["login_submit_enabled"] = bool(
                submits[0].is_enabled()
                and submits[0].get_attribute("aria-disabled") != "true"
            )
        state["continue_control_visible"] = any(
            label in {"weiter", "fortfahren", "weiter zu aldi talk", "zum kundenkonto"}
            for label in labels
        )
        state["consent_control_visible"] = any(
            label in {"zulassen", "bestätigen", "zustimmen", "einverstanden"}
            for label in labels
        )
        state["logout_visible"] = any(
            label in {"abmelden", "logout"} for label in labels
        )
    except Exception:
        pass
    try:
        state["frame_count"] = len(driver.find_elements("css selector", "iframe"))
    except Exception:
        pass
    try:
        ready = driver.execute_script("return document.readyState")
        state["document_ready"] = ready if ready in {"loading", "interactive", "complete"} else "unknown"
    except Exception:
        pass
    state.update(_network_state(driver))
    return state


def _webdriver_error_class(exc):
    name = type(exc).__name__
    return name if name in _ALLOWED_WEBDRIVER_ERRORS else 'WebDriverException'


def main():
    started = utcnow()
    report = {
        "started_at": started,
        "provider": "aldi_talk",
        "mode": "read_only_auth_probe",
        "auto_booking": {"enabled": False, "executed": False},
        "login_ok": False,
        "status": "error",
    }
    driver = None
    try:
        if not watcher.configure_credentials("ALDI"):
            report.update(status="config_error", reason="credentials_missing")
            return 3
        driver = watcher.build_driver()
        try:
            login_ok = watcher.aldi_login(driver)
        except TimeoutException:
            report.update(status="auth_timeout", reason="session_validation_timeout")
            report.update(_structural_state(driver))
            return 1
        except WebDriverException as exc:
            report.update(
                status="browser_error",
                reason="webdriver_error",
                webdriver_error_class=_webdriver_error_class(exc),
            )
            report.update(_structural_state(driver))
            return 1

        if not login_ok:
            report.update(status="auth_failed", reason="login_not_confirmed")
            report.update(_structural_state(driver))
            return 1

        report["login_ok"] = True
        report.update(_structural_state(driver))
        usage = watcher.aldi_read_status(driver)
        report.update(safe_refill_evidence("aldi_talk", usage))
        report.update(status="ok", reason="authenticated_read_only_probe_complete")
        return 0
    except PermissionError:
        report.update(status="auth_failed", reason="unexpected_origin_or_session")
        if driver is not None:
            report.update(_structural_state(driver))
        return 1
    except ValueError:
        report.update(status="validation_failed", reason="protected_data_not_unambiguous")
        if driver is not None:
            report.update(_structural_state(driver))
        return 1
    except Exception:
        report.update(status="error", reason="internal_error")
        if driver is not None:
            report.update(_structural_state(driver))
        return 1
    finally:
        report["finished_at"] = utcnow()
        write_report(REPORT, report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
