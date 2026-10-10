"""Inspect public ALDI login controls without credentials or submission.

This helper never loads secrets, never types into fields and never submits any
form. It records only public visible labels/text after the login widget has
finished rendering, plus frame metadata.
"""

import json
import os
from datetime import datetime, timezone

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from browser_dom import element_label, find_visible_elements, rendered_text
from monitoring import navigate, require_origin
import watcher


REPORT_PATH = os.getenv("ALDI_PUBLIC_CONTROLS_REPORT", "aldi-public-login-controls.json")


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_url(url):
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(url or "")
        return {"host": parsed.hostname, "path": parsed.path[:160]}
    except Exception:
        return {"host": None, "path": None}


def controls(driver):
    result = []
    for element in find_visible_elements(driver, "a,button,[role='button'],input[type='submit']")[:50]:
        try:
            label = element_label(driver, element).strip()
            if label:
                result.append({
                    "tag": (element.tag_name or "")[:16],
                    "label": label[:200],
                    "enabled": bool(element.is_enabled()) and element.get_attribute("aria-disabled") != "true",
                })
        except Exception:
            continue
    return result


def text_preview(driver):
    try:
        # This page is public and no credentials are ever typed by this script.
        return rendered_text(driver).strip()[:2500]
    except Exception:
        return ""


def main():
    report = {
        "started_at": now(),
        "finished_at": None,
        "typed_credentials": False,
        "submitted": False,
        "outcome": "unknown",
        "top_url": None,
        "top_text": "",
        "top_controls": [],
        "frames": [],
        "exception_type": None,
    }
    driver = None
    try:
        driver = watcher.build_driver()
        navigate(driver, watcher.ALDI_LOGIN_URL)
        require_origin(driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS)
        watcher.dismiss_cookie_banner(driver)

        # ALDI's SSO shell appears before the actual login widget. Wait for the
        # public username field so the scan reflects the same rendered state used
        # by the production login path.
        WebDriverWait(driver, 30).until(
            lambda _: len(find_visible_elements(
                driver,
                "input[autocomplete='username'],input[type='tel'],input[type='text']",
            )) >= 1
        )

        report["top_url"] = safe_url(driver.current_url)
        report["top_text"] = text_preview(driver)
        report["top_controls"] = controls(driver)

        for index, frame in enumerate(driver.find_elements(By.CSS_SELECTOR, "iframe")[:8]):
            row = {
                "index": index,
                "visible": False,
                "src": safe_url(frame.get_attribute("src") or ""),
                "text": "",
                "controls": [],
                "switch_error": None,
            }
            try:
                row["visible"] = bool(frame.is_displayed())
                if row["visible"]:
                    driver.switch_to.frame(frame)
                    row["text"] = text_preview(driver)
                    row["controls"] = controls(driver)
                    driver.switch_to.default_content()
            except Exception as exc:
                row["switch_error"] = type(exc).__name__
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
            report["frames"].append(row)

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
