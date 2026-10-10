"""Inspect ALDI TALK's current password-reset form without submitting it.

The probe performs no account change: it loads the login page, follows only a
visible password-reset navigation control, records sanitized field/control
shapes and exits before typing or submitting any personal data.
"""

import json
import os
from datetime import datetime, timezone

from browser_dom import element_label, find_visible_elements
from monitoring import navigate, require_origin
import watcher


REPORT_PATH = os.getenv("ALDI_RESET_PROBE_REPORT", "aldi-password-reset-probe.json")


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_host_path(url):
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(url or "")
        return {"host": parsed.hostname, "path": parsed.path[:160]}
    except Exception:
        return {"host": None, "path": None}


def main():
    report = {
        "started_at": now(),
        "finished_at": None,
        "outcome": "unknown",
        "reset_navigation_candidate_count": 0,
        "reset_navigation_clicked": False,
        "typed_personal_data": False,
        "submitted": False,
        "url": None,
        "fields": [],
        "controls": {},
        "exception_type": None,
    }
    driver = None
    try:
        driver = watcher.build_driver()
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)

        reset_links = []
        for control in find_visible_elements(driver, "a,button,[role='button']"):
            try:
                label = element_label(driver, control).strip().casefold()
                # This remains deliberately strict. Multiple rendered controls
                # with the same reset intent are harmless; none of them submits
                # credentials or changes account state by itself.
                if "passwort" in label and any(word in label for word in ("vergessen", "zurücksetzen", "zuruecksetzen")):
                    reset_links.append(control)
            except Exception:
                continue
        report["reset_navigation_candidate_count"] = len(reset_links)
        if not reset_links:
            report["outcome"] = "reset_navigation_missing"
            return 2

        # Navigation only; no account-changing submit occurs here. If the UI
        # renders duplicate reset controls, follow the first strict match.
        driver.execute_script("arguments[0].click();", reset_links[0])
        report["reset_navigation_clicked"] = True

        import time
        time.sleep(2)
        require_origin(driver, getattr(driver, "current_url", ""), login_hosts=watcher.ALDI_LOGIN_HOSTS)
        report["url"] = safe_host_path(getattr(driver, "current_url", ""))

        for field in find_visible_elements(driver, "input,select,textarea")[:12]:
            report["fields"].append({
                "tag": (field.tag_name or "")[:16],
                "type": (field.get_attribute("type") or "")[:24],
                "autocomplete": (field.get_attribute("autocomplete") or "")[:32],
                "inputmode": (field.get_attribute("inputmode") or "")[:24],
                "required": bool(field.get_attribute("required")),
                "maxlength": field.get_attribute("maxlength"),
            })

        categories = {
            "continue": ("weiter", "fortfahren"),
            "send": ("senden", "abschicken"),
            "confirm": ("bestätigen", "bestaetigen"),
            "back": ("zurück", "zurueck", "abbrechen"),
        }
        for control in find_visible_elements(driver, "a,button,[role='button'],input[type='submit']")[:24]:
            try:
                label = element_label(driver, control).strip().casefold()
                for category, words in categories.items():
                    if any(word in label for word in words):
                        row = report["controls"].setdefault(category, {"count": 0, "enabled_count": 0})
                        row["count"] += 1
                        if control.is_enabled() and control.get_attribute("aria-disabled") != "true":
                            row["enabled_count"] += 1
            except Exception:
                continue

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
