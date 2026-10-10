"""Collect sanitized ALDI SSO diagnostics without booking anything.

The probe performs exactly one login submission and then observes the browser
state for a bounded period. It never clicks or activates any refill control.
Secrets, field values, cookie values, query strings and fragments are never
written to the report.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from browser_dom import element_label, find_visible_elements, rendered_text
from monitoring import navigate, require_origin
import watcher


OBSERVE_SECONDS = int(os.getenv("ALDI_SSO_OBSERVE_SECONDS", "120"))
SAMPLE_SECONDS = max(2, int(os.getenv("ALDI_SSO_SAMPLE_SECONDS", "5")))
PROBE_AFTER_SECONDS = max(5, int(os.getenv("ALDI_SSO_PROBE_AFTER_SECONDS", "15")))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _scrub_path(path):
    parts = []
    for part in (path or "/").split("/"):
        if not part:
            parts.append("")
            continue
        if len(part) > 40 or re.fullmatch(r"[A-Fa-f0-9]{24,}", part) or re.fullmatch(r"[A-Za-z0-9_-]{48,}", part):
            parts.append(":opaque")
        else:
            parts.append(part[:80])
    return "/".join(parts) or "/"


def safe_url(url):
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(url or "")
        return {
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "path": _scrub_path(parsed.path),
        }
    except Exception:
        return {"scheme": None, "host": None, "path": None}


def _count_visible(driver, selector):
    try:
        return len(find_visible_elements(driver, selector))
    except Exception:
        return None


def _visible_input_shapes(driver):
    """Return form structure only; never values, names, ids or placeholders."""
    rows = []
    try:
        for element in find_visible_elements(driver, "input,select,textarea")[:12]:
            rows.append({
                "tag": (element.tag_name or "").lower(),
                "type": (element.get_attribute("type") or "").lower()[:24],
                "autocomplete": (element.get_attribute("autocomplete") or "").lower()[:32],
                "inputmode": (element.get_attribute("inputmode") or "").lower()[:24],
                "required": bool(element.get_attribute("required")),
                "enabled": bool(element.is_enabled()),
            })
    except Exception:
        pass
    return rows


def _iframe_shapes(driver):
    rows = []
    try:
        for frame in driver.find_elements(By.CSS_SELECTOR, "iframe")[:8]:
            rows.append({
                "src": safe_url(frame.get_attribute("src") or ""),
                "visible": bool(frame.is_displayed()),
            })
    except Exception:
        pass
    return rows


def _control_categories(driver):
    """Classify visible controls using an allowlist; never persist raw labels."""
    categories = {}
    rules = {
        "login": ("anmelden", "einloggen", "login"),
        "continue": ("weiter", "fortfahren", "continue", "nächste", "naechste"),
        "confirm": ("bestätigen", "bestaetigen", "confirm", "verifizieren"),
        "consent": ("zustimmen", "erlauben", "akzeptieren", "accept"),
        "cancel": ("abbrechen", "zurück", "zurueck", "cancel"),
        "code": ("code", "otp", "tan", "sms"),
        "retry": ("erneut", "noch einmal", "wiederholen", "retry"),
    }
    try:
        controls = find_visible_elements(driver, "button,a,[role='button'],input[type='submit']")[:30]
        for control in controls:
            try:
                label = element_label(driver, control).strip().casefold()
                enabled = bool(control.is_enabled()) and control.get_attribute("aria-disabled") != "true"
                for category, markers in rules.items():
                    if any(marker in label for marker in markers):
                        row = categories.setdefault(category, {"count": 0, "enabled_count": 0})
                        row["count"] += 1
                        if enabled:
                            row["enabled_count"] += 1
            except Exception:
                continue
    except Exception:
        pass
    return categories


def _page_flags(driver):
    flags = {
        "error_text": False,
        "captcha_text": False,
        "mfa_text": False,
        "sms_text": False,
        "code_text": False,
        "continue_text": False,
        "consent_text": False,
    }
    try:
        text = rendered_text(driver).casefold()
        flags["error_text"] = any(marker in text for marker in (
            "fehler", "fehlgeschlagen", "ungültig", "ungueltig", "gesperrt", "nicht möglich", "nicht moeglich"
        ))
        flags["captcha_text"] = any(marker in text for marker in ("captcha", "ich bin kein roboter", "robot"))
        flags["mfa_text"] = any(marker in text for marker in ("zwei-faktor", "2-faktor", "2fa", "verifizierung", "sicherheitscode"))
        flags["sms_text"] = "sms" in text
        flags["code_text"] = any(marker in text for marker in ("code", "tan", "otp"))
        flags["continue_text"] = any(marker in text for marker in ("weiter", "fortfahren", "continue"))
        flags["consent_text"] = any(marker in text for marker in ("zustimmen", "erlauben", "akzeptieren"))
    except Exception:
        pass
    return flags


def refill_evidence(driver):
    """Return booleans/counts only; never copy tariff or control text to logs."""
    result = {
        "unlimited_detected": False,
        "free_one_gb_control_count": 0,
    }
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text.casefold()
        result["unlimited_detected"] = "unlimited" in body_text

        matches = []
        for control in find_visible_elements(driver, "button,a,[role='button'],input[type='submit']"):
            try:
                label = element_label(driver, control).strip().casefold()
                exactly_one_gb = bool(re.search(r"(?<![\d.,])1(?:[.,]0+)?\s*gb\b", label))
                free_price = any(marker in label for marker in (
                    "kostenlos", "0 €", "0,00 €", "0.00 €", "0,- €", "0,-"
                ))
                enabled = control.is_enabled() and control.get_attribute("aria-disabled") != "true"
                if exactly_one_gb and free_price and enabled:
                    matches.append(control)
            except Exception:
                continue
        result["free_one_gb_control_count"] = len(matches)
    except Exception:
        pass
    return result


def snapshot(driver, elapsed):
    snap = {
        "elapsed_s": round(elapsed, 1),
        "url": safe_url(getattr(driver, "current_url", "")),
        "username_fields": _count_visible(driver, "input[autocomplete='username'],input[type='tel'],input[type='text']"),
        "password_fields": _count_visible(driver, "input[type='password']"),
        "alert_like_elements": _count_visible(driver, "[role='alert'],[aria-live='assertive'],[aria-live='polite']"),
        "buttons": _count_visible(driver, "button,[role='button'],input[type='submit']"),
        "input_shapes": _visible_input_shapes(driver),
        "iframe_shapes": _iframe_shapes(driver),
        "control_categories": _control_categories(driver),
        "page_flags": _page_flags(driver),
    }
    snap.update(refill_evidence(driver))
    try:
        snap["ready_state"] = driver.execute_script("return document.readyState")
    except Exception:
        snap["ready_state"] = None
    return snap


def network_summary(driver):
    rows = []
    seen = set()
    try:
        logs = driver.get_log("performance")
    except Exception:
        return rows

    allowed_suffixes = (
        "alditalk-kundenportal.de",
        "alditalk-kundenbetreuung.de",
        "alditalk.de",
    )
    for item in logs:
        try:
            message = json.loads(item.get("message", "{}"))["message"]
            method = message.get("method")
            params = message.get("params", {})
            if method == "Network.requestWillBeSent":
                req = params.get("request", {})
                safe = safe_url(req.get("url"))
                host = safe.get("host") or ""
                if not host.endswith(allowed_suffixes):
                    continue
                row = {
                    "event": "request",
                    "method": req.get("method"),
                    "url": safe,
                    "resource_type": params.get("type"),
                }
            elif method == "Network.responseReceived":
                resp = params.get("response", {})
                safe = safe_url(resp.get("url"))
                host = safe.get("host") or ""
                if not host.endswith(allowed_suffixes):
                    continue
                row = {
                    "event": "response",
                    "status": resp.get("status"),
                    "url": safe,
                    "resource_type": params.get("type"),
                }
            else:
                continue
            key = json.dumps(row, sort_keys=True)
            if key not in seen:
                seen.add(key)
                rows.append(row)
        except Exception:
            continue
    return rows[-120:]


def confirmed_portal_session(driver):
    return watcher.aldi_session_visible(driver)


def main():
    report_path = os.getenv("ALDI_SSO_REPORT", "aldi-sso-diagnostic.json")
    report = {
        "started_at": utcnow(),
        "finished_at": None,
        "booking_executed": False,
        "login_submit_count": 0,
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
    try:
        driver = watcher.build_driver()
        watcher.WAIT_TIMEOUT = max(watcher.WAIT_TIMEOUT, 30)
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)
        wait = WebDriverWait(driver, 30)

        def unique_enabled(selector):
            require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
            elements = find_visible_elements(driver, selector)
            return elements[0] if len(elements) == 1 and elements[0].is_enabled() else False

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
            require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
            controls = [
                e for e in find_visible_elements(driver, "button,a,[role='button'],input[type='submit']")
                if element_label(driver, e).strip().casefold() == "anmelden"
                and e.is_enabled() and e.get_attribute("aria-disabled") != "true"
            ]
            return controls[0] if len(controls) == 1 else False

        wait.until(trusted_submit)
        # Exactly one login submission. Never retry an uncertain submit.
        password = wait.until(lambda _: unique_enabled("input[type='password']"))
        password.send_keys(Keys.ENTER)
        report["login_submit_count"] = 1

        start = time.monotonic()
        protected_probe_done = False
        while True:
            elapsed = time.monotonic() - start
            report["samples"].append(snapshot(driver, elapsed))

            if confirmed_portal_session(driver):
                report["outcome"] = "portal_session_confirmed"
                break

            if not protected_probe_done and elapsed >= PROBE_AFTER_SECONDS:
                protected_probe_done = True
                report["protected_probe_count"] = 1
                navigate(driver, watcher.ALDI_OVERVIEW_URL, attempts=1)
                report["samples"].append(snapshot(driver, time.monotonic() - start))
                if confirmed_portal_session(driver):
                    report["outcome"] = "portal_session_confirmed"
                    break

            if elapsed >= OBSERVE_SECONDS:
                report["outcome"] = "sso_timeout"
                break
            time.sleep(SAMPLE_SECONDS)

        report["network"] = network_summary(driver)
    except Exception as exc:
        report["outcome"] = "exception"
        report["exception_type"] = type(exc).__name__
        if driver is not None:
            try:
                report["samples"].append(snapshot(driver, -1))
                report["network"] = network_summary(driver)
            except Exception:
                pass
    finally:
        report["finished_at"] = utcnow()
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        latest = report["samples"][-1] if report["samples"] else {}
        print(json.dumps({
            "outcome": report["outcome"],
            "login_submit_count": report["login_submit_count"],
            "protected_probe_count": report["protected_probe_count"],
            "sample_count": len(report["samples"]),
            "network_event_count": len(report["network"]),
            "unlimited_detected": bool(latest.get("unlimited_detected")),
            "free_one_gb_control_count": int(latest.get("free_one_gb_control_count") or 0),
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
