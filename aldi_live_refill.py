"""Guarded live runner for ALDI TALK's repeated free 1-GB refill.

This module is intentionally separate from monitoring.py. It can perform a
provider-changing action only when AUTO_BOOK_ENABLED=true and the authenticated
portal proves a unique enabled 1-GB refill with an explicit free/0-EUR price.
Paid or ambiguous offers are never clicked.
"""

import json
import math
import os
import re
import time
from datetime import datetime, timezone

from browser_dom import element_label
from core.aldi_refill import locate_selenium
from monitoring import require_origin
import watcher


REPORT_PATH = os.getenv("ALDI_LIVE_REPORT", "aldi-live-refill.json")
MAX_REFILLS_PER_RUN = max(1, min(5, int(os.getenv("ALDI_MAX_REFILLS_PER_RUN", "2"))))
CLICK_SETTLE_SECONDS = max(1, min(15, int(os.getenv("ALDI_CLICK_SETTLE_SECONDS", "3"))))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _write(report):
    temporary = REPORT_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, REPORT_PATH)


def _valid_remaining(value):
    return (not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0)


def _safe_status(driver):
    status = watcher.aldi_read_status(driver)
    remaining = status.get("inland_frei_gb")
    if not _valid_remaining(remaining):
        raise ValueError("remaining_volume_unverified")
    return float(remaining)


def _action_kind(driver, control):
    try:
        label = element_label(driver, control).casefold()
    except Exception:
        return "unknown"
    if re.search(r"\b(?:bestätigen|bestaetigen|confirm|weiter)\b", label):
        return "confirm"
    if re.search(r"\b(?:nachbuchen|buchen)\b|(?<!\d)\+\s*1\s*GB\b", label):
        return "book"
    return "unknown"


def _trusted_click(driver, control):
    """Activate exactly one already-validated control with a trusted pointer."""
    require_origin(driver, watcher.ALDI_OVERVIEW_URL)
    if (not control.is_enabled()
            or control.get_attribute("aria-disabled") == "true"
            or control.get_attribute("disabled") is not None):
        raise RuntimeError("validated_control_became_disabled")

    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center',inline:'center'});", control
    )
    time.sleep(0.2)
    rect = driver.execute_script(
        "const r=arguments[0].getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height};",
        control,
    )
    if not rect or rect.get("w", 0) <= 1 or rect.get("h", 0) <= 1:
        raise RuntimeError("validated_control_not_rendered")
    x = float(rect["x"]) + float(rect["w"]) / 2.0
    y = float(rect["y"]) + float(rect["h"]) / 2.0
    if x < 0 or y < 0:
        raise RuntimeError("validated_control_outside_viewport")

    # CDP input events are real browser pointer input. Never fall back to a DOM
    # click if this fails: an uncertain provider-changing action stays fail-closed.
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": x, "y": y, "button": "none"
    })
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y,
        "button": "left", "clickCount": 1
    })
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y,
        "button": "left", "clickCount": 1
    })


def main():
    report = {
        "started_at": utcnow(),
        "finished_at": None,
        "outcome": "unknown",
        "booking_enabled": os.getenv("AUTO_BOOK_ENABLED", "false").lower() == "true",
        "booking_clicks": 0,
        "confirmation_clicks": 0,
        "successful_refills": 0,
        "cycles": [],
    }
    driver = None

    try:
        if not report["booking_enabled"]:
            report["outcome"] = "booking_disabled"
            return 3
        if not watcher.configure_credentials("ALDI"):
            report["outcome"] = "credentials_unavailable"
            return 3

        driver = watcher.build_driver()
        if not watcher.aldi_login(driver):
            report["outcome"] = "auth_failed"
            return 2

        before = _safe_status(driver)
        # Verified Tarif S terms allow a refill at exactly 1.00 GB (<= 1 GB).
        if before > 1.0:
            report["outcome"] = "not_needed"
            report["remaining_gb"] = round(before, 3)
            return 0

        for cycle_index in range(MAX_REFILLS_PER_RUN):
            evidence, control = locate_selenium(driver, before)
            cycle = {
                "index": cycle_index + 1,
                "before_gb": round(before, 3),
                "eligibility": evidence.get("refill_reason"),
                "candidate_count": evidence.get("refill_candidate_count", 0),
                "tariff_evidence": evidence.get("tariff_evidence"),
                "action": None,
                "after_gb": None,
                "verified": False,
            }
            report["cycles"].append(cycle)
            _write(report)

            if not evidence.get("refill_eligible") or control is None:
                report["outcome"] = "free_refill_unavailable"
                return 0

            action = _action_kind(driver, control)
            if action != "book":
                report["outcome"] = "booking_control_unverified"
                cycle["action"] = action
                return 2

            cycle["action"] = "book"
            _trusted_click(driver, control)
            report["booking_clicks"] += 1
            _write(report)
            time.sleep(CLICK_SETTLE_SECONDS)

            # Some portal versions may present one explicit confirmation step.
            # Only accept it when the same free 1-GB detector still validates the
            # page and the control is clearly a confirmation control.
            try:
                confirm_evidence, confirm_control = locate_selenium(driver, before)
                if confirm_evidence.get("refill_eligible") and confirm_control is not None:
                    if _action_kind(driver, confirm_control) == "confirm":
                        _trusted_click(driver, confirm_control)
                        report["confirmation_clicks"] += 1
                        _write(report)
                        time.sleep(CLICK_SETTLE_SECONDS)
            except Exception:
                # Verification below decides the result. Never repeat the booking
                # click merely because confirmation inspection was inconclusive.
                pass

            try:
                after = _safe_status(driver)
            except Exception:
                report["outcome"] = "unknown_after_click"
                return 2

            cycle["after_gb"] = round(after, 3)
            increased = after >= before + 0.5
            cycle["verified"] = increased
            _write(report)
            if not increased:
                report["outcome"] = "unknown_after_click"
                return 2

            report["successful_refills"] += 1
            before = after
            # At exactly 1.00 GB the contract still allows another free refill;
            # only stop automatically once remaining volume is above 1 GB.
            if before > 1.0:
                report["outcome"] = "refill_verified"
                return 0

        # The run limit is not a failure. A later trigger may perform another free
        # refill if ALDI still proves eligibility and remaining volume is <= 1 GB.
        report["outcome"] = "run_limit_reached"
        return 0
    except Exception as exc:
        report["outcome"] = "error"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        report["finished_at"] = utcnow()
        _write(report)
        print(json.dumps({
            "outcome": report["outcome"],
            "booking_enabled": report["booking_enabled"],
            "booking_clicks": report["booking_clicks"],
            "confirmation_clicks": report["confirmation_clicks"],
            "successful_refills": report["successful_refills"],
        }, ensure_ascii=False), flush=True)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
