"""Sanitized no-submit ALDI login-identifier diagnostic.

Loads only the public login form and classifies the configured login identifier.
It never types credentials, never submits the form and never changes provider
state. No identifier digits, password, cookie values or tokens are reported.
"""

import json
import os
import re
from datetime import datetime, timezone

from browser_dom import find_visible_elements
from monitoring import navigate, require_origin
import watcher


REPORT_PATH = os.getenv("ALDI_LOGIN_FORMAT_REPORT", "aldi-login-format.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def classify_identifier(value):
    compact = re.sub(r"[\s()\-/]", "", value or "")
    if re.fullmatch(r"\+49\d+", compact):
        return "international_plus49"
    if re.fullmatch(r"0049\d+", compact):
        return "international_0049"
    if re.fullmatch(r"0\d+", compact):
        return "national_zero"
    if re.fullmatch(r"\d+", compact):
        return "digits_without_zero"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", compact):
        return "opaque_username"
    return "other"


def main():
    report = {
        "started_at": _now(),
        "finished_at": None,
        "outcome": "unknown",
        "submitted": False,
        "typed_credentials": False,
        "identifier_format": None,
        "identifier_length_bucket": None,
        "username_field": None,
        "exception_type": None,
    }

    if not watcher.configure_credentials("ALDI"):
        report["outcome"] = "credentials_unavailable"
        report["finished_at"] = _now()
        _write(report)
        return 3

    identifier = watcher.ALDI_USER
    report["identifier_format"] = classify_identifier(identifier)
    compact_len = len(re.sub(r"\s", "", identifier or ""))
    if compact_len <= 8:
        report["identifier_length_bucket"] = "short"
    elif compact_len <= 12:
        report["identifier_length_bucket"] = "phone_national_range"
    elif compact_len <= 15:
        report["identifier_length_bucket"] = "phone_international_range"
    else:
        report["identifier_length_bucket"] = "long"

    driver = None
    try:
        driver = watcher.build_driver()
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)
        fields = find_visible_elements(
            driver,
            "input[autocomplete='username'],input[type='tel'],input[type='text']",
        )
        if len(fields) != 1:
            report["outcome"] = "username_field_ambiguous"
            return 2
        field = fields[0]
        raw_pattern = field.get_attribute("pattern") or ""
        # Patterns can be useful for format diagnosis; only preserve a conservative
        # character set and bounded length so page content cannot leak through.
        safe_pattern = raw_pattern if re.fullmatch(r"[0-9A-Za-z\\+*?{}()[\]|.^$-]{0,120}", raw_pattern) else None
        report["username_field"] = {
            "type": (field.get_attribute("type") or "")[:24],
            "inputmode": (field.get_attribute("inputmode") or "")[:24],
            "autocomplete": (field.get_attribute("autocomplete") or "")[:32],
            "maxlength": field.get_attribute("maxlength"),
            "minlength": field.get_attribute("minlength"),
            "pattern": safe_pattern,
        }
        report["outcome"] = "observed"
        return 0
    except Exception as exc:
        report["outcome"] = "error"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        report["finished_at"] = _now()
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
