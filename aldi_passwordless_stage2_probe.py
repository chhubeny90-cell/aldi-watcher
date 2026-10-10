"""Request one ALDI TALK passwordless SMS code and inspect the next form safely.

The probe uses the configured ALDI account identifier, requests at most one
confirmation code, never logs the identifier, never types a code and never
performs a booking action. It will not click while ALDI marks the send control
aria-disabled. Only sanitized field/control shapes are saved.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from browser_dom import element_label, find_visible_elements, rendered_text
from monitoring import navigate, require_origin
import watcher


REPORT_PATH = os.getenv("ALDI_PASSWORDLESS_STAGE2_REPORT", "aldi-passwordless-stage2.json")


def now():
    return datetime.now(timezone.utc).isoformat()


def _find_control(driver, expected_label):
    matches = []
    wanted = expected_label.strip().casefold()
    for control in find_visible_elements(driver, "a,button,[role='button'],input[type='submit']"):
        try:
            if element_label(driver, control).strip().casefold() == wanted:
                matches.append(control)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def _control_enabled(control):
    if control is None:
        return False
    try:
        return (bool(control.is_enabled())
                and control.get_attribute("aria-disabled") != "true"
                and control.get_attribute("disabled") is None)
    except Exception:
        return False


def _passwordless_link(driver):
    matches = []
    for control in find_visible_elements(driver, "a,button,[role='button']"):
        try:
            if element_label(driver, control).strip().casefold().startswith("anmelden ohne passwort"):
                matches.append(control)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def _safe_text(value, limit):
    value = " ".join((value or "").split())
    return value[:limit]


def _field_shapes(driver):
    result = []
    for field in find_visible_elements(driver, "input,textarea,select")[:12]:
        try:
            accessible = _safe_text(getattr(field, "accessible_name", ""), 80)
        except Exception:
            accessible = ""
        result.append({
            "tag": (field.tag_name or "")[:16],
            "type": (field.get_attribute("type") or "")[:24],
            "autocomplete": (field.get_attribute("autocomplete") or "")[:32],
            "inputmode": (field.get_attribute("inputmode") or "")[:24],
            "required": bool(field.get_attribute("required")),
            "maxlength": (field.get_attribute("maxlength") or "")[:8],
            "placeholder": _safe_text(field.get_attribute("placeholder"), 80),
            "aria_label": _safe_text(field.get_attribute("aria-label"), 80),
            "accessible_name": accessible,
            "readonly": bool(field.get_attribute("readonly")),
            "disabled": not field.is_enabled(),
        })
    return result


def _control_labels(driver):
    labels = []
    for control in find_visible_elements(driver, "a,button,[role='button'],input[type='submit']")[:30]:
        try:
            label = element_label(driver, control).strip()
            if label:
                labels.append(label[:120])
        except Exception:
            continue
    return labels


def _identifier_variants(value):
    """Return common German phone representations without ever reporting values."""
    compact = re.sub(r"[\s()\-/]", "", value or "")
    variants = []

    def add(kind, candidate):
        if candidate and candidate not in [v for _, v in variants]:
            variants.append((kind, candidate))

    add("configured", compact)
    if compact.startswith("+49") and len(compact) > 3:
        add("national_zero", "0" + compact[3:])
        add("international_0049", "0049" + compact[3:])
        add("digits_without_country_plus", "49" + compact[3:])
    elif compact.startswith("0049") and len(compact) > 4:
        add("national_zero", "0" + compact[4:])
        add("international_plus49", "+49" + compact[4:])
        add("digits_without_country_plus", "49" + compact[4:])
    elif compact.startswith("49") and len(compact) > 2:
        add("national_zero", "0" + compact[2:])
        add("international_plus49", "+49" + compact[2:])
        add("international_0049", "0049" + compact[2:])
    elif compact.startswith("0") and len(compact) > 1:
        add("international_plus49", "+49" + compact[1:])
        add("international_0049", "0049" + compact[1:])
        add("digits_without_country_plus", "49" + compact[1:])
    return variants[:4]


def _set_field(field, value):
    field.send_keys(Keys.CONTROL, "a")
    field.send_keys(Keys.BACKSPACE)
    field.send_keys(value)
    field.send_keys(Keys.TAB)


def _field_valid(driver, field):
    try:
        return bool(driver.execute_script("return arguments[0].checkValidity();", field))
    except Exception:
        return None


def main():
    report = {
        "started_at": now(),
        "finished_at": None,
        "outcome": "unknown",
        "navigation_clicked": False,
        "identifier_typed": False,
        "identifier_variant_selected": None,
        "variant_checks": [],
        "code_requested": False,
        "code_typed": False,
        "submit_method": "dom_click_after_explicit_enablement",
        "submit_state_before_click": None,
        "field_shapes": [],
        "control_labels": [],
        "text_flags": {},
        "page_host": None,
        "exception_type": None,
    }
    driver = None
    try:
        identifier = (os.getenv("ALDI_USER") or os.getenv("ALDI_LOGIN_USER") or "").strip()
        if not identifier:
            report["outcome"] = "identifier_unavailable"
            return 3

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
        link = WebDriverWait(driver, 10).until(lambda _: _passwordless_link(driver) or False)
        driver.execute_script("arguments[0].click();", link)
        report["navigation_clicked"] = True

        field = WebDriverWait(driver, 10).until(
            lambda _: (lambda items: items[0] if len(items) == 1 and items[0].is_enabled() else False)(
                find_visible_elements(driver, "input[type='tel'],input[autocomplete='tel']")
            )
        )
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)

        selected = None
        submit = None
        for kind, candidate in _identifier_variants(identifier):
            _set_field(field, candidate)
            report["identifier_typed"] = True
            time.sleep(0.7)
            submit = _find_control(driver, "Bestätigungscode senden")
            enabled = _control_enabled(submit)
            report["variant_checks"].append({
                "kind": kind,
                "html_valid": _field_valid(driver, field),
                "submit_enabled": enabled,
                "aria_disabled": None if submit is None else submit.get_attribute("aria-disabled") == "true",
            })
            if enabled:
                selected = kind
                break

        report["identifier_variant_selected"] = selected
        if selected is None or submit is None:
            report["outcome"] = "send_control_not_enabled"
            report["field_shapes"] = _field_shapes(driver)
            report["control_labels"] = _control_labels(driver)
            return 4

        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        report["submit_state_before_click"] = {
            "enabled": _control_enabled(submit),
            "aria_disabled": submit.get_attribute("aria-disabled") == "true",
            "tag": (submit.tag_name or "")[:16],
            "role": (submit.get_attribute("role") or "")[:24],
        }
        # This exact Shadow-DOM action is intentionally invoked only after ALDI
        # itself has removed aria-disabled. One submission maximum per run.
        driver.execute_script("arguments[0].click();", submit)
        report["code_requested"] = True

        # Observe only the resulting code-entry form. Never enter a code here.
        time.sleep(3)
        WebDriverWait(driver, 10).until(lambda _: len(find_visible_elements(driver, "input")) >= 1)
        report["field_shapes"] = _field_shapes(driver)
        report["control_labels"] = _control_labels(driver)
        try:
            text = rendered_text(driver).casefold()
        except Exception:
            text = ""
        report["text_flags"] = {
            "sms": "sms" in text,
            "code": any(word in text for word in ("code", "tan", "einmalcode", "bestätigungscode")),
            "resend": any(word in text for word in ("erneut", "noch einmal", "nochmal", "neuen code")),
            "expired": "abgelaufen" in text,
        }
        try:
            from urllib.parse import urlsplit
            host = urlsplit(driver.current_url).hostname
            report["page_host"] = host if host in {
                "www.alditalk-kundenportal.de", "login.alditalk-kundenbetreuung.de"
            } else "other"
        except Exception:
            report["page_host"] = "unknown"
        report["outcome"] = "observed_after_enabled_submit"
        return 0
    except Exception as exc:
        report["outcome"] = "error"
        report["exception_type"] = type(exc).__name__
        try:
            if driver is not None:
                report["field_shapes"] = _field_shapes(driver)
                report["control_labels"] = _control_labels(driver)
        except Exception:
            pass
        return 2
    finally:
        report["finished_at"] = now()
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
