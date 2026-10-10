"""Sanitized ALDI SSO diagnostic using the production DOM-click submit path.

Exactly one login click is performed. No refill control is touched. The report
contains only booleans/types/HTTP statuses, never credentials, token values,
cookie values, query strings or raw response bodies.
"""

import json
import os
import time

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

import aldi_sso_diagnostic as diag
from browser_dom import element_label, find_visible_elements
from monitoring import navigate, require_origin
import watcher


REPORT_PATH = os.getenv("ALDI_SSO_REPORT", "aldi-sso-diagnostic.json")
OBSERVE_SECONDS = max(15, min(60, int(os.getenv("ALDI_SSO_OBSERVE_SECONDS", "30"))))


def main():
    report = {
        "started_at": diag.utcnow(),
        "finished_at": None,
        "booking_executed": False,
        "login_submit_count": 0,
        "submit_method": "validated_login_control_dom_click",
        "credential_field_state": None,
        "auth_request_shapes": [],
        "auth_response_shapes": [],
        "protected_probe_count": 0,
        "outcome": "unknown",
        "samples": [],
        "network": [],
        "exception_type": None,
    }
    if not watcher.configure_credentials("ALDI"):
        report["outcome"] = "credentials_unavailable"
        _finish(report)
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
        report["credential_field_state"] = {
            "username_matches_secret": user.get_attribute("value") == watcher.ALDI_USER,
            "password_matches_secret": password.get_attribute("value") == watcher.ALDI_PASS,
            "submit_enabled": bool(submit.is_enabled()) and submit.get_attribute("aria-disabled") != "true",
        }

        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        driver.execute_script("arguments[0].click();", submit)
        report["login_submit_count"] = 1

        started = time.monotonic()
        while True:
            elapsed = time.monotonic() - started
            diag.drain_network(driver, report, seen)
            report["samples"].append(diag.snapshot(driver, elapsed))
            if watcher.aldi_session_visible(driver):
                report["outcome"] = "portal_session_confirmed"
                break
            if elapsed >= OBSERVE_SECONDS:
                report["outcome"] = "sso_timeout"
                break
            time.sleep(2)
        diag.drain_network(driver, report, seen)
    except Exception as exc:
        report["outcome"] = "exception"
        report["exception_type"] = type(exc).__name__
        if driver is not None:
            try:
                diag.drain_network(driver, report, seen)
            except Exception:
                pass
    finally:
        report["finished_at"] = diag.utcnow()
        _finish(report)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
    return 0 if report["outcome"] == "portal_session_confirmed" else 2


def _finish(report):
    with open(REPORT_PATH, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    latest = report["samples"][-1] if report["samples"] else {}
    print(json.dumps({
        "outcome": report["outcome"],
        "submit_method": report["submit_method"],
        "credential_field_state": report["credential_field_state"],
        "auth_request_shapes": report["auth_request_shapes"],
        "auth_response_shapes": report["auth_response_shapes"],
        "last_alert_category": latest.get("alert_category", {}),
        "booking_executed": False,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
