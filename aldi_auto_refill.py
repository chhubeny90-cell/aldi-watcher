"""Guarded ALDI TALK automatic free 1-GB refill.

This runner is intentionally separate from the legacy provider plugin. It only
performs one native click when all of these facts are proven in the authenticated
portal immediately before the click:

* exact active account match,
* exactly one explicit 1-GB refill offer,
* price is explicitly 0 EUR or "kostenlos",
* no paid/abo/conflicting wording,
* exactly one enabled booking control scoped to that offer.

The workflow persists a PENDING state before execution. Any ambiguous outcome is
UNKNOWN and is never clicked again until the portal itself reconciles the refill
through an approximately +1 GB change in remaining data.
"""

import argparse
import hashlib
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from browser_dom import element_label, find_visible_elements
from core.aldi_refill import inspect_selenium, protected_session_visible
from core.aldi_selector_probe import probe_selectors, sanitized_probe
from monitoring import write_report
import watcher


STATE_VERSION = 1
PLAN_VERSION = 1
MIN_CONFIRM_DELTA_GB = 0.90
_REQUIRED_SELECTOR_ROLES = (
    "account", "active_tariff", "refill_offer", "refill_button"
)
_BOOK_LABEL = re.compile(r"\b(?:nachbuchen|buchen|aktivieren)\b", re.I)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except Exception:
            pass


def _load_json(path):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def load_state(path):
    target = Path(path)
    if not target.exists():
        return None
    try:
        state = _load_json(target)
    except Exception as exc:
        raise RuntimeError("state_unreadable") from exc
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise RuntimeError("state_invalid")
    if state.get("status") not in {"READY", "PENDING", "UNKNOWN", "SUCCESS"}:
        raise RuntimeError("state_invalid")
    return state


def selector_plan(probe):
    """Return four unique sanitized selectors or None."""
    if not isinstance(probe, dict):
        return None
    selectors = {}
    for role in _REQUIRED_SELECTOR_ROLES:
        item = probe.get(role, {})
        unique = item.get("unique") if isinstance(item, dict) else None
        if not isinstance(unique, str) or not unique:
            return None
        selectors[role] = unique
    return selectors


def selector_digest(selectors):
    encoded = json.dumps(selectors, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def refill_confirmed(before_gb, after_gb, minimum_delta_gb=MIN_CONFIRM_DELTA_GB):
    values = (before_gb, after_gb, minimum_delta_gb)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        return False
    if not all(math.isfinite(float(value)) for value in values):
        return False
    if before_gb < 0 or after_gb < 0 or minimum_delta_gb <= 0:
        return False
    return float(after_gb) - float(before_gb) >= float(minimum_delta_gb)


def _safe_remaining(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def _read_remaining(driver):
    status = watcher.aldi_read_status(driver)
    return _safe_remaining(status.get("inland_frei_gb"))


def _discover(driver):
    probe = sanitized_probe(probe_selectors(driver, watcher.ALDI_USER))
    counts = {
        role: int(probe.get(role, {}).get("count", 0))
        for role in _REQUIRED_SELECTOR_ROLES
    }
    return selector_plan(probe), counts


def _open_authenticated_driver():
    if not watcher.configure_credentials("ALDI"):
        raise RuntimeError("credentials_unavailable")
    driver = watcher.build_driver()
    try:
        if not watcher.aldi_login(driver):
            raise RuntimeError("login_failed")
        if not protected_session_visible(driver):
            raise RuntimeError("session_unverified")
        return driver
    except Exception:
        try:
            driver.quit()
        except Exception:
            pass
        raise


def _report(path, status, reason, **extra):
    allowed = {
        "status": status,
        "reason": reason,
        "at": utcnow(),
        "auto_refill_enabled": os.getenv("ALDI_AUTO_REFILL_ENABLED", "false").lower() == "true",
    }
    for key, value in extra.items():
        if key in {
            "attempt_id", "selector_counts", "before_remaining_gb",
            "after_remaining_gb", "booking_executed", "state_status",
        }:
            allowed[key] = value
    write_report(path, allowed)
    print(json.dumps(allowed, ensure_ascii=False), flush=True)


def _bootstrap_state(path):
    state = {
        "version": STATE_VERSION,
        "initialized": True,
        "status": "READY",
        "attempt_id": None,
        "before_remaining_gb": None,
        "selector_digest": None,
        "prepared_at": None,
        "finished_at": None,
        "last_observed_remaining_gb": None,
        "last_reason": "bootstrap",
    }
    _atomic_json(path, state)
    return state


def _mark_ready(state_path, state, reason):
    state.update(
        status="READY",
        attempt_id=None,
        before_remaining_gb=None,
        selector_digest=None,
        prepared_at=None,
        last_reason=reason,
    )
    _atomic_json(state_path, state)


def prepare(state_path, plan_path, report_path):
    if os.getenv("ALDI_AUTO_REFILL_ENABLED", "false").strip().lower() != "true":
        _report(report_path, "BLOCKED", "auto_refill_disabled", booking_executed=False)
        return 0

    state = load_state(state_path)
    if state is None:
        _bootstrap_state(state_path)
        _report(report_path, "BOOTSTRAPPED", "state_initialized_no_click", booking_executed=False)
        return 0

    driver = None
    try:
        driver = _open_authenticated_driver()
        remaining = _read_remaining(driver)

        if state["status"] in {"PENDING", "UNKNOWN"}:
            baseline = _safe_remaining(state.get("before_remaining_gb"))
            if baseline is not None and remaining is not None and refill_confirmed(baseline, remaining):
                state.update(
                    status="SUCCESS",
                    finished_at=utcnow(),
                    last_observed_remaining_gb=remaining,
                    last_reason="reconciled_by_volume",
                )
                _atomic_json(state_path, state)
                _report(
                    report_path, "SUCCESS", "previous_attempt_reconciled",
                    attempt_id=state.get("attempt_id"),
                    before_remaining_gb=baseline,
                    after_remaining_gb=remaining,
                    booking_executed=False,
                    state_status="SUCCESS",
                )
            else:
                state.update(
                    status="UNKNOWN",
                    last_observed_remaining_gb=remaining,
                    last_reason="previous_attempt_unresolved",
                )
                _atomic_json(state_path, state)
                _report(
                    report_path, "BLOCKED", "previous_attempt_unresolved",
                    attempt_id=state.get("attempt_id"),
                    before_remaining_gb=baseline,
                    after_remaining_gb=remaining,
                    booking_executed=False,
                    state_status="UNKNOWN",
                )
            return 0

        selectors, counts = _discover(driver)
        if selectors is None:
            _report(
                report_path, "BLOCKED", "selector_ambiguity",
                selector_counts=counts, booking_executed=False,
                state_status=state["status"],
            )
            return 0

        evidence = inspect_selenium(driver, watcher.ALDI_USER, selectors)
        if not (
            evidence.get("account_verified") is True
            and evidence.get("refill_eligible") is True
            and evidence.get("refill_type") == "FREE_ONE_GB"
            and evidence.get("refill_reason") == "free_one_gb_offer_available"
        ):
            _report(
                report_path, "NOOP", evidence.get("refill_reason", "offer_unverified"),
                selector_counts=counts, booking_executed=False,
                state_status=state["status"],
            )
            return 0

        if remaining is None:
            _report(
                report_path, "BLOCKED", "remaining_volume_unverified",
                selector_counts=counts, booking_executed=False,
                state_status=state["status"],
            )
            return 0

        attempt_id = uuid4().hex
        digest = selector_digest(selectors)
        state.update(
            status="PENDING",
            attempt_id=attempt_id,
            before_remaining_gb=remaining,
            selector_digest=digest,
            prepared_at=utcnow(),
            finished_at=None,
            last_observed_remaining_gb=remaining,
            last_reason="prepared_before_click",
        )
        _atomic_json(state_path, state)
        _atomic_json(plan_path, {
            "version": PLAN_VERSION,
            "attempt_id": attempt_id,
            "selector_digest": digest,
            "selectors": selectors,
        })
        _report(
            report_path, "PREPARED", "verified_free_one_gb",
            attempt_id=attempt_id, selector_counts=counts,
            before_remaining_gb=remaining, booking_executed=False,
            state_status="PENDING",
        )
        return 0
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def execute(state_path, plan_path, report_path):
    if os.getenv("ALDI_AUTO_REFILL_ENABLED", "false").strip().lower() != "true":
        _report(report_path, "BLOCKED", "auto_refill_disabled", booking_executed=False)
        return 0

    if not Path(plan_path).exists():
        state = load_state(state_path)
        _report(
            report_path, "NOOP", "no_prepared_booking",
            booking_executed=False,
            state_status=state.get("status") if state else None,
        )
        return 0

    state = load_state(state_path)
    plan = _load_json(plan_path)
    if (
        state is None
        or state.get("status") != "PENDING"
        or not isinstance(plan, dict)
        or plan.get("version") != PLAN_VERSION
        or plan.get("attempt_id") != state.get("attempt_id")
        or plan.get("selector_digest") != state.get("selector_digest")
    ):
        _report(report_path, "BLOCKED", "plan_state_mismatch", booking_executed=False)
        return 0

    planned_selectors = plan.get("selectors")
    if not isinstance(planned_selectors, dict) or selector_digest(planned_selectors) != state.get("selector_digest"):
        _report(report_path, "BLOCKED", "plan_invalid", booking_executed=False)
        return 0

    driver = None
    click_started = False
    observed_after = None
    try:
        driver = _open_authenticated_driver()
        baseline = _safe_remaining(state.get("before_remaining_gb"))
        current = _read_remaining(driver)
        if baseline is None or current is None:
            _mark_ready(state_path, state, "pre_click_volume_unverified")
            _report(report_path, "BLOCKED", "pre_click_volume_unverified", booking_executed=False, state_status="READY")
            return 0

        if refill_confirmed(baseline, current):
            state.update(
                status="SUCCESS", finished_at=utcnow(),
                last_observed_remaining_gb=current,
                last_reason="external_or_previous_refill_reconciled_before_click",
            )
            _atomic_json(state_path, state)
            _report(
                report_path, "SUCCESS", "already_reconciled_before_click",
                attempt_id=state.get("attempt_id"),
                before_remaining_gb=baseline, after_remaining_gb=current,
                booking_executed=False, state_status="SUCCESS",
            )
            return 0

        selectors, counts = _discover(driver)
        if selectors is None or selector_digest(selectors) != state.get("selector_digest"):
            _mark_ready(state_path, state, "pre_click_selector_changed")
            _report(
                report_path, "BLOCKED", "pre_click_selector_changed",
                selector_counts=counts, booking_executed=False, state_status="READY",
            )
            return 0

        evidence = inspect_selenium(driver, watcher.ALDI_USER, selectors)
        if not (
            evidence.get("account_verified") is True
            and evidence.get("refill_eligible") is True
            and evidence.get("refill_type") == "FREE_ONE_GB"
            and evidence.get("refill_reason") == "free_one_gb_offer_available"
        ):
            _mark_ready(state_path, state, "pre_click_offer_changed")
            _report(
                report_path, "NOOP", evidence.get("refill_reason", "offer_unverified"),
                selector_counts=counts, booking_executed=False, state_status="READY",
            )
            return 0

        offers = find_visible_elements(driver, selectors["refill_offer"])
        if len(offers) != 1:
            _mark_ready(state_path, state, "pre_click_offer_ambiguous")
            _report(report_path, "BLOCKED", "pre_click_offer_ambiguous", booking_executed=False, state_status="READY")
            return 0
        buttons = find_visible_elements(driver, selectors["refill_button"], scope=offers[0])
        if len(buttons) != 1:
            _mark_ready(state_path, state, "pre_click_button_ambiguous")
            _report(report_path, "BLOCKED", "pre_click_button_ambiguous", booking_executed=False, state_status="READY")
            return 0
        button = buttons[0]
        label = element_label(driver, button)
        enabled = (
            button.is_enabled()
            and button.get_attribute("aria-disabled") != "true"
            and button.get_attribute("disabled") is None
        )
        if not enabled or not _BOOK_LABEL.search(label or ""):
            _mark_ready(state_path, state, "pre_click_button_unverified")
            _report(report_path, "BLOCKED", "pre_click_button_unverified", booking_executed=False, state_status="READY")
            return 0

        # One and only one booking action. No click retry and no JS fallback.
        click_started = True
        button.click()

        for delay in (2, 4, 8, 12):
            time.sleep(delay)
            try:
                driver.refresh()
                from selenium.webdriver.support.ui import WebDriverWait
                WebDriverWait(driver, 30).until(protected_session_visible)
                observed_after = _read_remaining(driver)
            except Exception:
                observed_after = None
            if observed_after is not None and refill_confirmed(baseline, observed_after):
                state.update(
                    status="SUCCESS",
                    finished_at=utcnow(),
                    last_observed_remaining_gb=observed_after,
                    last_reason="free_one_gb_reconciled_by_volume",
                )
                _atomic_json(state_path, state)
                _report(
                    report_path, "SUCCESS", "free_one_gb_reconciled",
                    attempt_id=state.get("attempt_id"),
                    before_remaining_gb=baseline,
                    after_remaining_gb=observed_after,
                    booking_executed=True,
                    state_status="SUCCESS",
                )
                return 0

        state.update(
            status="UNKNOWN",
            finished_at=utcnow(),
            last_observed_remaining_gb=observed_after,
            last_reason="post_click_outcome_unknown",
        )
        _atomic_json(state_path, state)
        print("::warning::ALDI refill click occurred but provider reconciliation is still UNKNOWN; no automatic retry will be made.")
        _report(
            report_path, "UNKNOWN", "post_click_outcome_unknown",
            attempt_id=state.get("attempt_id"),
            before_remaining_gb=baseline,
            after_remaining_gb=observed_after,
            booking_executed=True,
            state_status="UNKNOWN",
        )
        return 0
    except Exception as exc:
        if click_started:
            state.update(
                status="UNKNOWN",
                finished_at=utcnow(),
                last_observed_remaining_gb=observed_after,
                last_reason="exception_after_click",
            )
            _atomic_json(state_path, state)
            print("::warning::Exception after booking click; state forced to UNKNOWN and retries are blocked.")
            _report(
                report_path, "UNKNOWN", "exception_after_click",
                attempt_id=state.get("attempt_id"),
                booking_executed=True, state_status="UNKNOWN",
            )
            return 0
        _mark_ready(state_path, state, "exception_before_click")
        _report(
            report_path, "BLOCKED", "exception_before_click",
            booking_executed=False, state_status="READY",
        )
        return 0
    finally:
        try:
            Path(plan_path).unlink(missing_ok=True)
        except Exception:
            pass
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "execute"])
    parser.add_argument("--state", default=".state/aldi-booking-state.json")
    parser.add_argument("--plan", default=".state/aldi-booking-plan.json")
    parser.add_argument("--report", default="auto-refill-report.json")
    args = parser.parse_args(argv)
    if args.mode == "prepare":
        return prepare(args.state, args.plan, args.report)
    return execute(args.state, args.plan, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
