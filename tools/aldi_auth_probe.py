"""Sanitized ALDI authentication probe for GitHub Actions.

The probe performs the same account login as watcher.py but never books or
clicks a refill control. On authentication failure it emits only structural,
allowlisted booleans/counts so SSO/MFA/error states can be distinguished
without exposing account data, page text, URLs, cookies, or tokens.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from selenium.common.exceptions import TimeoutException, WebDriverException

import watcher
from browser_dom import element_label, find_visible_elements
from monitoring import safe_refill_evidence, utcnow, write_report


REPORT = Path("monitoring-report.json")


def _visible(elements):
    result = []
    for element in elements:
        try:
            if element.is_displayed():
                result.append(element)
        except Exception:
            continue
    return result


def _host_class(driver):
    try:
        host = urlsplit(driver.current_url).hostname
    except Exception:
        return "unknown"
    if host == "login.alditalk-kundenbetreuung.de":
        return "aldi_sso"
    if host == "www.alditalk-kundenportal.de":
        return "aldi_portal"
    return "other"


def _structural_state(driver):
    """Return only non-secret structural indicators from the current page."""
    state = {
        "host_class": _host_class(driver),
        "cookie_count": None,
        "visible_input_count": None,
        "visible_password_count": None,
        "mfa_input_visible": False,
        "alert_region_visible": False,
        "invalid_input_count": None,
        "login_submit_visible": False,
        "login_submit_enabled": False,
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
        submits = [element for element in controls
                   if element_label(driver, element).strip().casefold() == "anmelden"]
        state["login_submit_visible"] = len(submits) == 1
        if len(submits) == 1:
            state["login_submit_enabled"] = bool(
                submits[0].is_enabled()
                and submits[0].get_attribute("aria-disabled") != "true"
            )
        state["logout_visible"] = any(
            element_label(driver, element).strip().casefold() in {"abmelden", "logout"}
            for element in controls
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
    return state


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
        except WebDriverException:
            report.update(status="browser_error", reason="webdriver_error")
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
