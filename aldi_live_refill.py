"""Guarded live runner for ALDI TALK's repeated free 1-GB refill.

This module is intentionally separate from monitoring.py. It can perform a
provider-changing action only when AUTO_BOOK_ENABLED=true and the authenticated
portal proves a unique enabled 1-GB refill with verified free entitlement.
Paid or ambiguous offers are never clicked.
"""

import json
import math
import os
import re
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from browser_dom import element_label
from core.aldi_refill import (locate_selenium, tariff_identity_selenium,
                              verify_account_selenium)
from monitoring import diagnostics, require_origin
import watcher
from core.database import Database, RechargeLockedError
from core.aldi_http_login import LoginError, phone_identifier


# Historical receipt reconciliation is unavailable. This is a factual capability,
# not the user's booking switch; NEW operations have separate volume confirmation.
ALDI_RECONCILIATION_VERIFIED = False

REPORT_PATH = os.getenv("ALDI_LIVE_REPORT", "aldi-live-refill.json")
MAX_REFILLS_PER_RUN = max(1, min(5, int(os.getenv("ALDI_MAX_REFILLS_PER_RUN", "2"))))
CLICK_SETTLE_SECONDS = max(1, min(15, int(os.getenv("ALDI_CLICK_SETTLE_SECONDS", "3"))))


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def open_live_journal():
    """Never silently replace a lost journal with an empty database."""
    path = Path(os.environ.get('ALDI_JOURNAL_PATH', ''))
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError('persistent_journal_unavailable')
    if os.name != 'posix' or path.stat().st_mode & 0o077:
        raise RuntimeError('private_posix_journal_required')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve()
        if (os.environ.get('RUNNER_ENVIRONMENT') != 'self-hosted'
                or path.resolve().is_relative_to(workspace)):
            raise RuntimeError('durable_runner_required')
    with sqlite3.connect(path.as_uri() + '?mode=rw', uri=True) as conn:
        conn.execute('SELECT recharge_id, status FROM recharges LIMIT 0')
    return Database(str(path))


def check_recharge_status(driver, recharge_id):
    """No verified ALDI lookup mapping our operation ID to a receipt exists yet.

    A current volume, absence of an offer or a generic success notice cannot
    resolve a historical operation with no trustworthy before-click baseline.
    Never invent an endpoint or infer FAILED from absence.
    """
    return 'UNKNOWN'


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


def _identity_proof(driver, account):
    """Private within-run identity; never copy these signatures into reports."""
    return (verify_account_selenium(driver, account), tariff_identity_selenium(driver))


def _bound_status(driver, account):
    # A cookie switch between the refresh and its volume read must not make an
    # allowance from a different SIM look like this operation's confirmation.
    previous_account = verify_account_selenium(driver, account)
    remaining = _safe_status(driver)
    binding = _identity_proof(driver, account)
    if previous_account != binding[0]:
        raise RuntimeError('account_changed_during_status_read')
    return remaining, binding


def _unresolved_aldi(db, account):
    """Do not hide old reservations behind a changed provider/account spelling."""
    relevant = []
    for record in db.get_unresolved_recharges():
        provider = re.sub(r'[^a-z0-9]', '', (record.provider or '').casefold())
        if provider in {'lidl', 'lidlconnect'}:
            continue
        # Only known ALDI names plus the exact configured phone can be associated
        # with this authenticated account. Unknown names/aliases require mapping;
        # never turn their absence from a filtered query into permission to book.
        if provider not in {'aldi', 'alditalk'}:
            raise RuntimeError('unresolved_account_mapping_required')
        try:
            same_account = phone_identifier(record.username) == account
        except (LoginError, TypeError):
            same_account = False
        if not same_account:
            raise RuntimeError('unresolved_account_mapping_required')
        relevant.append(record)
    return relevant


def _action_kind(driver, control):
    try:
        label = element_label(driver, control).casefold()
    except Exception:
        return "unknown"
    if re.search(r"\b(?:bestätigen|bestaetigen|confirm|weiter)\b", label, re.I):
        return "confirm"
    if re.search(r"\b(?:nachbuchen|buchen)\b|(?<!\d)\+\s*1\s*GB\b", label, re.I):
        return "book"
    return "unknown"


def _login_failure_outcome(driver):
    """Classify only sanitized cached auth evidence; never send a new request."""
    try:
        provider = diagnostics(driver).get('provider_indications') or {}
    except Exception:
        return 'auth_failed'
    return 'account_locked' if provider.get('account_locked') is True else 'auth_failed'


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
    db = None
    recharge_id = None

    try:
        if not report["booking_enabled"]:
            report["outcome"] = "booking_disabled"
            return 3
        if not watcher.configure_credentials("ALDI"):
            report["outcome"] = "credentials_unavailable"
            return 3

        account = phone_identifier(watcher.ALDI_ACCOUNT_USER)
        db = open_live_journal()
        try:
            unresolved = _unresolved_aldi(db, account)
        except RuntimeError:
            report['outcome'] = 'unresolved_account_mapping_required'
            return 2

        # Recovery must use the same authenticated portal session as a normal
        # status check. If ALDI returns an account-lock indication, surface that
        # fixed state from cached diagnostics and never retry credentials here.
        driver = watcher.build_driver()
        try:
            logged_in = watcher.aldi_login(driver)
        except Exception:
            outcome = _login_failure_outcome(driver)
            if outcome == 'account_locked':
                report['outcome'] = outcome
                return 2
            raise
        if not logged_in:
            report["outcome"] = _login_failure_outcome(driver)
            return 2

        if unresolved:
            # An old operation has no trustworthy before/after baseline. A new
            # volume increase or reoffered button never releases its reservation.
            verify_account_selenium(driver, account)
            for record in unresolved:
                status = check_recharge_status(driver, record.recharge_id)
                if status not in {'SUCCESS', 'FAILED', 'UNKNOWN'}:
                    status = 'UNKNOWN'
                db.set_recharge_status(record.recharge_id, status)

            # Recovery is always a recovery-only run. Even when every old
            # operation reaches a terminal state, a fresh booking waits for a
            # separate run and a fresh eligibility check.
            if _unresolved_aldi(db, account):
                report['outcome'] = 'unresolved_recharge_blocked'
                return 2
            report['outcome'] = 'recovery_complete'
            return 0

        before, binding = _bound_status(driver, account)
        # ALDI allows the free refill only below 1 GB; exactly 1 GB is not eligible.
        if before >= 1.0:
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

            # Revalidate identity and the complete priced offer immediately before
            # reserving/clicking. The protected account GET is read-only and uses
            # this browser session; no permanent portal polling is introduced.
            if _identity_proof(driver, account) != binding:
                report['outcome'] = 'identity_changed_before_click'
                return 2
            current_evidence, current_control = locate_selenium(driver, before)
            if (current_evidence.get('refill_eligible') is not True
                    or current_control is None
                    or _action_kind(driver, current_control) != 'book'
                    or tariff_identity_selenium(driver) != binding[1]):
                report['outcome'] = 'offer_changed_before_click'
                return 2
            control = current_control

            cycle["action"] = "book"
            try:
                if _unresolved_aldi(db, account):
                    report['outcome'] = 'unresolved_recharge_blocked'
                    return 2
            except RuntimeError:
                report['outcome'] = 'unresolved_account_mapping_required'
                return 2
            # Keep the cross-run cooldown, but an independently verified NEW success
            # in this run may be followed by the next eligible refill.
            same_run_success = report["successful_refills"] > 0
            recharge_id = db.begin_recharge(
                'alditalk', account,
                recent_success_guard_seconds=0 if same_run_success else 30,
            )
            cycle['recharge_id'] = recharge_id
            cycle['recharge_status'] = 'PENDING'
            _write(report)
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
                        if _identity_proof(driver, account) != binding:
                            raise RuntimeError('identity_changed_before_confirmation')
                        # The account GET can outlive a DOM re-render or price
                        # change. Reacquire and reprice the confirmation afterwards.
                        fresh_evidence, fresh_control = locate_selenium(driver, before)
                        if (fresh_evidence.get('refill_eligible') is not True
                                or fresh_control is None
                                or _action_kind(driver, fresh_control) != 'confirm'
                                or tariff_identity_selenium(driver) != binding[1]):
                            raise RuntimeError('confirmation_changed_before_click')
                        _trusted_click(driver, fresh_control)
                        report["confirmation_clicks"] += 1
                        _write(report)
                        time.sleep(CLICK_SETTLE_SECONDS)
            except Exception:
                # Verification below decides the result. Never repeat the booking
                # click merely because confirmation inspection was inconclusive.
                pass

            try:
                # This navigates afresh to the protected provider overview. Bind
                # that refreshed allowance to the same SIM/subscription/tariff.
                after, after_binding = _bound_status(driver, account)
            except Exception:
                report["outcome"] = "unknown_after_click"
                return 2

            cycle["after_gb"] = round(after, 3)
            cycle['volume_increased'] = after > before
            delta = after - before
            # The Masterprompt permits refreshed allowance as independent proof
            # for this NEW one-click operation. It is never a historical receipt.
            status = ('SUCCESS' if after_binding == binding and 0 < delta <= 1.0 + 1e-6
                      else 'UNKNOWN')
            cycle['recharge_status'] = db.set_recharge_status(recharge_id, status)
            cycle['verified'] = status == 'SUCCESS'
            cycle['confirmation'] = 'refreshed_volume' if status == 'SUCCESS' else 'unverified'
            _write(report)
            if status != 'SUCCESS':
                report["outcome"] = "unknown_after_click"
                return 2

            report["successful_refills"] += 1
            before = after
            # Stop at 1 GB or more; ALDI permits another free refill only below 1 GB.
            if before >= 1.0:
                report["outcome"] = "refill_verified"
                return 0

        # The run limit is not a failure. A later trigger may perform another free
        # refill if ALDI still proves eligibility and remaining volume is < 1 GB.
        report["outcome"] = "run_limit_reached"
        return 0
    except RechargeLockedError:
        report['outcome'] = 'recharge_locked'
        return 2
    except Exception as exc:
        report["outcome"] = "error"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        if db is not None and recharge_id is not None:
            # Late UNKNOWN cannot overwrite a verified terminal outcome.
            try:
                db.set_recharge_status(recharge_id, 'UNKNOWN')
            except Exception:
                # A failed update leaves durable PENDING blocking the account.
                report['outcome'] = 'journal_update_failed'
        report["finished_at"] = utcnow()
        try:
            _write(report)
            print(json.dumps({
                "outcome": report["outcome"],
                "booking_enabled": report["booking_enabled"],
                "booking_clicks": report["booking_clicks"],
                "confirmation_clicks": report["confirmation_clicks"],
                "successful_refills": report["successful_refills"],
            }, ensure_ascii=False), flush=True)
        finally:
            try:
                if driver is not None:
                    driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())