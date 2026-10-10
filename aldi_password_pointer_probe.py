"""Sanitized ALDI password login using ALDI's observed two-stage auth tree.

The first trusted pointer interaction is accepted only as an auth-tree
initialization when ALDI returns stage-loginPage without an error. Credentials
are then rebound after the component render and submitted exactly once. No
booking control is inspected or activated. Reports contain booleans/structure
only, never credential, cookie, token, query-string or raw response-body values.
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


def _fill_credentials(driver, wait):
    user = wait.until(lambda _: _unique_enabled(driver, "input[autocomplete='username'],input[type='tel'],input[type='text']"))
    user.send_keys(Keys.CONTROL, "a"); user.send_keys(Keys.BACKSPACE); user.send_keys(watcher.ALDI_USER); user.send_keys(Keys.TAB)
    password = wait.until(lambda _: _unique_enabled(driver, "input[type='password']"))
    password.send_keys(Keys.CONTROL, "a"); password.send_keys(Keys.BACKSPACE); password.send_keys(watcher.ALDI_PASS); password.send_keys(Keys.TAB)
    submit = wait.until(lambda _: _login_control(driver))
    user = wait.until(lambda _: _unique_enabled(driver, "input[autocomplete='username'],input[type='tel'],input[type='text']"))
    password = wait.until(lambda _: _unique_enabled(driver, "input[type='password']"))
    state = {
        "username_matches_secret": user.get_attribute("value") == watcher.ALDI_USER,
        "password_matches_secret": password.get_attribute("value") == watcher.ALDI_PASS,
        "submit_enabled": bool(_login_control(driver)),
    }
    return state, submit


def _latest_login_stage(report):
    for shape in reversed(report["auth_response_shapes"]):
        if shape.get("stage_identifier"):
            return shape
    return None


def _shape_has_auth_error(shape):
    category = (shape or {}).get("text_output_category") or {}
    return any(category.get(key) for key in (
        "invalid_credentials", "account_locked", "account_deactivated",
        "technical_error", "required_fields", "session_error", "unknown_error_text",
    ))


def main():
    report = {
        "started_at": utcnow(), "finished_at": None,
        "outcome": "unknown", "booking_executed": False,
        "pre_init_credential_state": None, "post_init_credential_state": None,
        "auth_tree_init_count": 0, "credential_submit_count": 0,
        "submit_method": "cdp_trusted_pointer_two_stage",
        "init_pointer_geometry": None, "credential_pointer_geometry": None,
        "portal_session": False,
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

        # Existing UI renders the fields before the ForgeRock/AM tree has been
        # initialized. Populate them only to make ALDI's login action available.
        state, submit = _fill_credentials(driver, wait)
        report["pre_init_credential_state"] = state
        if not all(state.values()):
            report["outcome"] = "pre_init_form_not_ready"
            return 4

        drain_network(driver, report, seen)
        report["init_pointer_geometry"] = _trusted_pointer_click(driver, submit)
        report["auth_tree_init_count"] = 1

        # The first interaction is considered initialization only if ALDI itself
        # returns the known login-page challenge without a failure category.
        init_deadline = time.monotonic() + 10
        init_shape = None
        while time.monotonic() < init_deadline:
            time.sleep(0.75)
            drain_network(driver, report, seen)
            init_shape = _latest_login_stage(report)
            if init_shape is not None:
                break
        if (init_shape is None or init_shape.get("stage_identifier") != "stage-loginPage"
                or init_shape.get("has_token_id") or _shape_has_auth_error(init_shape)):
            report["outcome"] = "auth_tree_init_unverified"
            return 2

        # The challenge may re-render the custom elements. Re-resolve and refill
        # from secrets, then submit credentials exactly once.
        state, submit = _fill_credentials(driver, wait)
        report["post_init_credential_state"] = state
        if not all(state.values()):
            report["outcome"] = "post_init_form_not_ready"
            return 4

        baseline_requests = len(report["auth_request_shapes"])
        baseline_responses = len(report["auth_response_shapes"])
        report["credential_pointer_geometry"] = _trusted_pointer_click(driver, submit)
        report["credential_submit_count"] = 1

        start = time.monotonic()
        while time.monotonic() - start < OBSERVE_SECONDS:
            time.sleep(1.25)
            drain_network(driver, report, seen)
            if watcher.aldi_session_visible(driver):
                report["portal_session"] = True
                report["outcome"] = "portal_session_confirmed"
                return 0
            new_responses = report["auth_response_shapes"][baseline_responses:]
            if any(shape.get("has_token_id") for shape in new_responses):
                report["outcome"] = "auth_token_observed_waiting_for_portal"
            if any(_shape_has_auth_error(shape) for shape in new_responses):
                report["outcome"] = "credential_response_rejected_or_error"
                return 2

        report["portal_session"] = watcher.aldi_session_visible(driver)
        if report["portal_session"]:
            report["outcome"] = "portal_session_confirmed"
            return 0
        if report["outcome"] == "auth_token_observed_waiting_for_portal":
            return 5
        if len(report["auth_request_shapes"]) <= baseline_requests:
            report["outcome"] = "credential_submit_no_auth_request"
        else:
            report["outcome"] = "credential_submit_no_confirmed_session"
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
            "pre_init_credential_state": report["pre_init_credential_state"],
            "post_init_credential_state": report["post_init_credential_state"],
            "auth_tree_init_count": report["auth_tree_init_count"],
            "credential_submit_count": report["credential_submit_count"],
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
