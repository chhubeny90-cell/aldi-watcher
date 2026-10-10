"""Inspect ALDI TALK's public "Anmelden ohne Passwort" flow without submit.

No secrets are loaded, no personal data is typed and no form is submitted. The
probe only navigates to the passwordless login screen and records sanitized
field/control shapes, submit structure and public JavaScript asset locations.
"""

import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from selenium.webdriver.common.by import By
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


def _safe_asset(url):
    try:
        parsed = urlsplit(url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        # Assets are public. Query/fragment are deliberately omitted.
        return {"host": parsed.hostname[:120], "path": (parsed.path or "/")[:220]}
    except Exception:
        return None


def _asset_sources(driver):
    rows = []
    seen = set()
    try:
        for element in driver.find_elements(By.CSS_SELECTOR, "script[src]")[:40]:
            safe = _safe_asset(element.get_attribute("src"))
            if safe and (safe["host"], safe["path"]) not in seen:
                seen.add((safe["host"], safe["path"]))
                rows.append(safe)
    except Exception:
        pass
    try:
        entries = driver.execute_script(
            "return performance.getEntriesByType('resource').map(e => e.name).filter(Boolean);"
        ) or []
        for url in entries:
            safe = _safe_asset(url)
            if not safe or not safe["path"].lower().endswith((".js", ".mjs")):
                continue
            key = (safe["host"], safe["path"])
            if key not in seen:
                seen.add(key)
                rows.append(safe)
    except Exception:
        pass
    return rows[:60]


def _submit_structure(driver, control):
    """Return only public structural metadata; never DOM text or field values."""
    raw = driver.execute_script(r"""
        const el = arguments[0];
        const row = {
          tag: (el.tagName || '').toLowerCase(),
          type: el.getAttribute('type') || '',
          role: el.getAttribute('role') || '',
          disabled: !!el.disabled,
          aria_disabled: el.getAttribute('aria-disabled') || '',
          onclick_attribute: el.hasAttribute('onclick'),
          form_present: !!el.form,
          form_method: el.form ? (el.form.method || '') : '',
          form_action_host: '',
          form_action_path: '',
          shadow_depth: 0,
          ancestor_tags: []
        };
        if (el.form && el.form.action) {
          try {
            const u = new URL(el.form.action, document.baseURI);
            row.form_action_host = u.hostname;
            row.form_action_path = u.pathname;
          } catch (_) {}
        }
        let current = el;
        for (let i = 0; current && i < 8; i++) {
          const root = current.getRootNode ? current.getRootNode() : null;
          const parent = current.parentElement || (root && root.host) || null;
          if (!parent) break;
          if (root && root.host && !current.parentElement) row.shadow_depth += 1;
          row.ancestor_tags.push((parent.tagName || '').toLowerCase());
          current = parent;
        }
        const r = el.getBoundingClientRect();
        row.rect_present = !!(r && r.width > 0 && r.height > 0);
        row.rect_width_bucket = r.width < 80 ? 'small' : (r.width < 240 ? 'medium' : 'wide');
        row.rect_height_bucket = r.height < 24 ? 'small' : (r.height < 64 ? 'medium' : 'tall');
        return row;
    """, control)
    if raw.get("form_action_host") not in {
        "www.alditalk-kundenportal.de", "login.alditalk-kundenbetreuung.de"
    }:
        raw["form_action_host"] = "other" if raw.get("form_action_host") else ""
    raw["form_action_path"] = (raw.get("form_action_path") or "")[:160]
    raw["ancestor_tags"] = [(x or "")[:40] for x in raw.get("ancestor_tags", [])[:8]]
    return raw


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
        "send_control_structure": None,
        "script_assets": [],
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

        send_matches = []
        for control in find_visible_elements(driver, "a,button,[role='button'],input[type='submit']")[:30]:
            try:
                label = element_label(driver, control).strip()
                if label:
                    report["control_labels"].append(label[:120])
                    if label.casefold() == "bestätigungscode senden":
                        send_matches.append(control)
            except Exception:
                continue
        if len(send_matches) == 1:
            report["send_control_structure"] = _submit_structure(driver, send_matches[0])

        report["script_assets"] = _asset_sources(driver)
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
