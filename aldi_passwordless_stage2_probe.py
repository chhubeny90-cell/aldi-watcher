"""Request one ALDI TALK passwordless SMS code and inspect the next form safely.

The probe uses the configured ALDI account identifier, requests exactly one
confirmation code, never reads or logs the identifier, never types a code and
never performs a booking action. Only sanitized field/control shapes are saved.
"""

import json
import os
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


def _unique_control(driver, expected_label):
    matches = []
    wanted = expected_label.strip().casefold()
    for control in find_visible_elements(driver, "a,button,[role='button'],input[type='submit']"):
        try:
            if element_label(driver, control).strip().casefold() == wanted and control.is_enabled():
                matches.append(control)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def _passwordless_link(driver):
    matches = []
    for control in find_visible_elements(driver, "a,button,[role='button']"):
        try:
            if element_label(driver, control).strip().casefold().startswith("anmelden ohne passwort"):
                matches.append(control)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def _field_shapes(driver):
    result = []
    for field in find_visible_elements(driver, "input,textarea,select")[:12]:
        result.append({
            "tag": (field.tag_name or "")[:16],
            "type": (field.get_attribute("type") or "")[:24],
            "autocomplete": (field.get_attribute("autocomplete") or "")[:32],
            "inputmode": (field.get_attribute("inputmode") or "")[:24],
            "required": bool(field.get_attribute("required")),
            "maxlength": (field.get_attribute("maxlength") or "")[:8],
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


def main():
    report = {
        "started_at": now(),
        "finished_at": None,
        "outcome": "unknown",
        "navigation_clicked": False,
        "identifier_typed": False,
        "code_requested": False,
        "code_typed": False,
        "field_shapes": [],
        "control_labels": [],
        "text_flags": {},
        "page_host": None,
        "exception_type": None,
    }
    driver = None
    try:
        identifier = "".join((os.getenv("ALDI_USER") or os.getenv("ALDI_LOGIN_USER") or "").split())
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
        field.send_keys(Keys.CONTROL, "a")
        field.send_keys(Keys.BACKSPACE)
        field.send_keys(identifier)
        field.send_keys(Keys.TAB)
        report["identifier_typed"] = True

        submit = WebDriverWait(driver, 10).until(
            lambda _: _unique_control(driver, "Bestätigungscode senden") or False
        )
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
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
        report["outcome"] = "observed"
        return 0
    except Exception as exc:
        report["outcome"] = "error"
        report["exception_type"] = type(exc).__name__
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
