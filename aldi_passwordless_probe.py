"""Inspect ALDI TALK's public "Anmelden ohne Passwort" flow without submit.

No secrets are loaded, no personal data is typed and no form is submitted. The
probe only navigates to the passwordless login screen and records sanitized
field/control shapes to determine whether the flow could be useful later.
"""

import json
import os
import time
from datetime import datetime, timezone

from selenium.webdriver.support.ui import WebDriverWait

from browser_dom import element_label, find_visible_elements, rendered_text
from monitoring import navigate, require_origin
import watcher


REPORT_PATH = os.getenv("ALDI_PASSWORDLESS_PROBE_REPORT", "aldi-passwordless-probe.json")


def now():
    return datetime.now(timezone.utc).isoformat()


def _passwordless_link(driver):
    matches = []
    for control in find_visible_elements(driver, "a,button,[role='button']"):
        try:
            label = element_label(driver, control).strip().casefold()
            if label.startswith("anmelden ohne passwort"):
                matches.append(control)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def main():
    report = {
        "started_at": now(),
        "finished_at": None,
        "outcome": "unknown",
        "navigation_clicked": False,
        "typed_personal_data": False,
        "submitted": False,
        "field_shapes": [],
        "control_labels": [],
        "text_flags": {},
        "exception_type": None,
    }
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
        link = WebDriverWait(driver, 10).until(lambda _: _passwordless_link(driver) or False)
        driver.execute_script("arguments[0].click();", link)
        report["navigation_clicked"] = True
        time.sleep(2)

        for field in find_visible_elements(driver, "input,textarea,select")[:12]:
            report["field_shapes"].append({
                "tag": (field.tag_name or "")[:16],
                "type": (field.get_attribute("type") or "")[:24],
                "autocomplete": (field.get_attribute("autocomplete") or "")[:32],
                "inputmode": (field.get_attribute("inputmode") or "")[:24],
                "required": bool(field.get_attribute("required")),
            })

        for control in find_visible_elements(driver, "a,button,[role='button'],input[type='submit']")[:30]:
            try:
                label = element_label(driver, control).strip()
                if label:
                    report["control_labels"].append(label[:120])
            except Exception:
                continue

        try:
            text = rendered_text(driver).casefold()
        except Exception:
            text = ""
        report["text_flags"] = {
            "sms": "sms" in text,
            "code": any(word in text for word in ("code", "tan", "einmalcode")),
            "email": "e-mail" in text or "email" in text,
            "limited_access": "eingeschränkten zugang" in text or "eingeschraenkten zugang" in text,
        }
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
