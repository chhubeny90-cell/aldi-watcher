"""Sanitized one-shot ALDI password login using a trusted Chrome pointer.

No booking controls are inspected or activated. Credentials are loaded only from
configured secrets. Reports contain booleans/structure only, never credential,
cookie, token, query-string or response-body values.
"""

import json
import os
import time
from datetime import datetime, timezone

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from browser_dom import element_label, find_visible_elements
from monitoring import navigate, require_origin
import watcher
from aldi_sso_diagnostic import drain_network

REPORT_PATH = os.getenv("ALDI_PASSWORD_POINTER_REPORT", "aldi-password-pointer.json")
OBSERVE_SECONDS = max(10, min(60, int(os.getenv("ALDI_PASSWORD_POINTER_SECONDS", "35"))))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _unique_enabled(driver, selector):
    require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
    items = find_visible_elements(driver, selector)
    return items[0] if len(items) == 1 and items[0].is_enabled() else False


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
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
    return {
        "width_bucket": "small" if rect["w"] < 80 else ("medium" if rect["w"] < 240 else "wide"),
        "height_bucket": "small" if rect["h"] < 24 else ("medium" if rect["h"] < 64 else "tall"),
    }


def main():
    report = {
        "started_at": utcnow(), "finished_at": None,
        "outcome": "unknown", "booking_executed": False,
        "credential_state": None, "submit_count": 0,
        "submit_method": "cdp_trusted_pointer_after_explicit_enablement",
        "pointer_geometry": None, "portal_session": False,
        "network": [], "auth_request_shapes": [], "auth_response_shapes": [],
        "exception_type": None,
    }
    if not watcher.configure_credentials("ALDI"):
        report["outcome"] = "credentials_unavailable"
        report["finished_at"] = utcnow()
        with open(REPORT_PATH, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 3

    driver = None
    seen = set()
    try:
        driver = watcher.build_driver()
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)
        wait = WebDriverWait(driver, 30)

        user = wait.until(lambda _: _unique_enabled(driver, "input[autocomplete='username'],input[type='tel'],input[type='text']"))
        user.send_keys(Keys.CONTROL, "a"); user.send_keys(Keys.BACKSPACE); user.send_keys(watcher.ALDI_USER); user.send_keys(Keys.TAB)
        password = wait.until(lambda _: _unique_enabled(driver, "input[type='password']"))
        password.send_keys(Keys.CONTROL, "a"); password.send_keys(Keys.BACKSPACE); password.send_keys(watcher.ALDI_PASS); password.send_keys(Keys.TAB)
        submit = wait.until(lambda _: _login_control(driver))

        # Re-resolve fields after component blur/re-render before comparing values.
        user = wait.until(lambda _: _unique_enabled(driver, "input[autocomplete='username'],input[type='tel'],input[type='text']"))
        password = wait.until(lambda _: _unique_enabled(driver, "input[type='password']"))
        report["credential_state"] = {
            "username_matches_secret": user.get_attribute("value") == watcher.ALDI_USER,
            "password_matches_secret": password.get_attribute("value") == watcher.ALDI_PASS,
            "submit_enabled": bool(_login_control(driver)),
        }
        if not all(report["credential_state"].values()):
            report["outcome"] = "credential_or_submit_not_ready"
            return 4

        # Drain initial navigation noise, then issue exactly one trusted pointer click.
        drain_network(driver, report, seen)
        report["pointer_geometry"] = _trusted_pointer_click(driver, submit)
        report["submit_count"] = 1

        start = time.monotonic()
        while time.monotonic() - start < OBSERVE_SECONDS:
            time.sleep(1.5)
            drain_network(driver, report, seen)
            if watcher.aldi_session_visible(driver):
                report["portal_session"] = True
                report["outcome"] = "portal_session_confirmed"
                return 0
            # A successful token-bearing auth response is useful evidence even
            # before the protected portal rendering has settled.
            if any(shape.get("has_token_id") for shape in report["auth_response_shapes"]):
                report["outcome"] = "auth_token_observed_waiting_for_portal"
        report["portal_session"] = watcher.aldi_session_visible(driver)
        if report["portal_session"]:
            report["outcome"] = "portal_session_confirmed"
            return 0
        if report["outcome"] == "auth_token_observed_waiting_for_portal":
            return 5
        report["outcome"] = "no_confirmed_session"
        return 2
    except Exception as exc:
        report["outcome"] = "exception"
        report["exception_type"] = type(exc).__name__
        if driver is not None:
            drain_network(driver, report, seen)
        return 2
    finally:
        report["finished_at"] = utcnow()
        with open(REPORT_PATH, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(json.dumps({
            "outcome": report["outcome"],
            "credential_state": report["credential_state"],
            "submit_count": report["submit_count"],
            "submit_method": report["submit_method"],
            "portal_session": report["portal_session"],
            "auth_request_shapes": report["auth_request_shapes"],
            "auth_response_shapes": report["auth_response_shapes"],
            "exception_type": report["exception_type"],
            "booking_executed": False,
        }, ensure_ascii=False), flush=True)
        if driver is not None:
            try: driver.quit()
            except Exception: pass


if __name__ == "__main__":
    raise SystemExit(main())
