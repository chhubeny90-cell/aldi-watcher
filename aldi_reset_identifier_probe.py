"""Validate the configured ALDI login identifier in the password-reset form.

This probe performs no account change. It opens the public password-reset form,
types only the configured ALDI login identifier, blurs the field, records
sanitized validity/submit-state booleans and exits without submitting.
No phone number, password, cookie value, token or reset code is written.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from browser_dom import element_label, find_visible_elements
from monitoring import navigate, require_origin
import watcher


REPORT_PATH = os.getenv("ALDI_RESET_IDENTIFIER_REPORT", "aldi-reset-identifier-probe.json")


def now():
    return datetime.now(timezone.utc).isoformat()


def _normalise_phone(value):
    compact = re.sub(r"[\s()\-/]", "", value or "")
    if compact.startswith("+49"):
        return "0" + compact[3:]
    if compact.startswith("0049"):
        return "0" + compact[4:]
    return compact


def _reset_link(driver):
    matches = []
    for control in find_visible_elements(driver, "a,button,[role='button']"):
        try:
            if element_label(driver, control).strip().casefold() == "passwort vergessen?":
                matches.append(control)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def _submit_state(driver):
    rows = []
    for control in find_visible_elements(driver, "button,[role='button'],input[type='submit'],a")[:30]:
        try:
            label = element_label(driver, control).strip().casefold()
            if any(word in label for word in ("senden", "bestätigen", "bestaetigen", "weiter", "fortfahren")):
                enabled = bool(control.is_enabled()) and control.get_attribute("aria-disabled") != "true" and control.get_attribute("disabled") is None
                rows.append({"enabled": enabled})
        except Exception:
            continue
    return {
        "candidate_count": len(rows),
        "enabled_count": sum(1 for row in rows if row["enabled"]),
    }


def main():
    report = {
        "started_at": now(),
        "finished_at": None,
        "outcome": "unknown",
        "typed_identifier": False,
        "submitted": False,
        "field_count": 0,
        "field_valid": None,
        "aria_invalid": None,
        "submit_state": None,
        "exception_type": None,
    }

    identifier = os.getenv("ALDI_LOGIN_USER") or os.getenv("ALDI_USER") or ""
    identifier = _normalise_phone(identifier)
    if not identifier:
        report["outcome"] = "identifier_unavailable"
        report["finished_at"] = now()
        _write(report)
        return 3

    driver = None
    try:
        driver = watcher.build_driver()
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)

        WebDriverWait(driver, 30).until(
            lambda _: len(find_visible_elements(
                driver,
                "input[autocomplete='username'],input[type='tel'],input[type='text']",
            )) >= 1
        )
        link = WebDriverWait(driver, 10).until(lambda _: _reset_link(driver) or False)
        driver.execute_script("arguments[0].click();", link)

        fields = WebDriverWait(driver, 15).until(
            lambda _: find_visible_elements(driver, "input,textarea,select") or False
        )
        report["field_count"] = len(fields)
        if len(fields) != 1:
            report["outcome"] = "reset_field_ambiguous"
            return 2

        field = fields[0]
        field.send_keys(Keys.CONTROL, "a")
        field.send_keys(Keys.BACKSPACE)
        field.send_keys(identifier)
        field.send_keys(Keys.TAB)
        report["typed_identifier"] = True
        time.sleep(1)

        try:
            report["field_valid"] = bool(driver.execute_script("return arguments[0].checkValidity ? arguments[0].checkValidity() : null;", field))
        except Exception:
            report["field_valid"] = None
        aria_invalid = field.get_attribute("aria-invalid")
        report["aria_invalid"] = None if aria_invalid is None else aria_invalid == "true"
        report["submit_state"] = _submit_state(driver)
        report["outcome"] = "observed"
        return 0
    except Exception as exc:
        report["outcome"] = "error"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        report["finished_at"] = now()
        _write(report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def _write(report):
    with open(REPORT_PATH, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
