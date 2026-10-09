"""Transactional, fail-closed ALDI free 1-GB browser booking.

This module never guesses provider selectors. It executes at most one click and
requires the same evidence gates as the read-only inspector plus a provider-side
success marker whose fingerprint changes after the click.
"""

import hashlib
from typing import Optional

from browser_dom import element_label, find_visible_elements, rendered_text
from core.aldi_refill import (
    configured_selectors,
    inspect_selenium,
    protected_session_visible,
    success_text_is_specific,
)
from monitoring import require_origin


class BookingBlockedError(RuntimeError):
    """Pre-click evidence is insufficient; no external side effect occurred."""


class BookingUnknownError(RuntimeError):
    """A click occurred but the provider outcome could not be reconciled."""


_REQUIRED_SELECTORS = (
    "account",
    "active_tariff",
    "refill_offer",
    "refill_button",
    "refill_success",
    "refill_reconcile",
)


def _unique(driver, selector, scope=None):
    elements = find_visible_elements(driver, selector, scope=scope)
    if len(elements) != 1:
        raise ValueError("ambiguous_or_hidden_element")
    return elements[0]


def _fingerprint(driver, element) -> str:
    """Hash provider markup in memory; never persist raw account/portal text."""
    text = " ".join(rendered_text(driver, element).split())
    try:
        html = driver.execute_script("return arguments[0].outerHTML || '';", element) or ""
    except Exception:
        html = ""
    return hashlib.sha256((text + "\n" + html).encode("utf-8")).hexdigest()


def reconciliation_snapshot(driver, expected_account, selectors=None):
    """Return NONE/SUCCESS/UNKNOWN plus an opaque hash for the reconcile marker."""
    from core.aldi_refill import normalize_msisdn

    selectors = configured_selectors() if selectors is None else selectors
    if not selectors.get("account") or not selectors.get("refill_reconcile"):
        return "UNKNOWN", None
    try:
        require_origin(driver, "https://www.alditalk-kundenportal.de/")
        if not protected_session_visible(driver):
            return "UNKNOWN", None
        account = _unique(driver, selectors["account"])
        if normalize_msisdn(rendered_text(driver, account)) != normalize_msisdn(expected_account):
            return "UNKNOWN", None
        markers = find_visible_elements(driver, selectors["refill_reconcile"])
        if len(markers) == 0:
            return "NONE", None
        if len(markers) != 1:
            return "UNKNOWN", None
        marker = markers[0]
        text = rendered_text(driver, marker)
        if not success_text_is_specific(text):
            return "UNKNOWN", None
        return "SUCCESS", _fingerprint(driver, marker)
    except Exception:
        return "UNKNOWN", None


def success_snapshot(driver, selectors=None):
    """Return NONE/SUCCESS/UNKNOWN for the transient post-click confirmation."""
    selectors = configured_selectors() if selectors is None else selectors
    selector = selectors.get("refill_success")
    if not selector:
        return "UNKNOWN", None
    try:
        require_origin(driver, "https://www.alditalk-kundenportal.de/")
        markers = find_visible_elements(driver, selector)
        if len(markers) == 0:
            return "NONE", None
        if len(markers) != 1:
            return "UNKNOWN", None
        marker = markers[0]
        text = rendered_text(driver, marker)
        if not success_text_is_specific(text):
            return "UNKNOWN", None
        return "SUCCESS", _fingerprint(driver, marker)
    except Exception:
        return "UNKNOWN", None


def _all_selectors_present(selectors) -> bool:
    return all(bool(selectors.get(key)) for key in _REQUIRED_SELECTORS)


def execute_free_one_gb_selenium(
    driver,
    expected_account,
    selectors=None,
    baseline_reconcile_fingerprint: Optional[str] = None,
    timeout_seconds: int = 30,
):
    """Execute exactly one verified free 1-GB click and reconcile the outcome.

    Returns an allowlisted result dictionary. Any error after the click becomes
    BookingUnknownError so callers must persist UNKNOWN and never retry blindly.
    """
    from selenium.webdriver.support.ui import WebDriverWait

    selectors = configured_selectors() if selectors is None else selectors
    if not _all_selectors_present(selectors):
        return {
            "booking_status": "BLOCKED",
            "booking_executed": False,
            "booking_reason": "selectors_unconfigured",
            "reconcile_fingerprint": baseline_reconcile_fingerprint,
        }

    evidence = inspect_selenium(driver, expected_account, selectors)
    if not (
        evidence.get("account_verified") is True
        and evidence.get("refill_eligible") is True
        and evidence.get("refill_type") == "FREE_ONE_GB"
        and evidence.get("refill_reason") == "free_one_gb_offer_available"
    ):
        return {
            "booking_status": "BLOCKED",
            "booking_executed": False,
            "booking_reason": evidence.get("refill_reason", "offer_unverified"),
            "reconcile_fingerprint": baseline_reconcile_fingerprint,
        }

    pre_status, pre_fingerprint = reconciliation_snapshot(driver, expected_account, selectors)
    if pre_status == "UNKNOWN":
        return {
            "booking_status": "BLOCKED",
            "booking_executed": False,
            "booking_reason": "reconciliation_unverified",
            "reconcile_fingerprint": baseline_reconcile_fingerprint,
        }
    if baseline_reconcile_fingerprint and pre_fingerprint != baseline_reconcile_fingerprint:
        return {
            "booking_status": "BLOCKED",
            "booking_executed": False,
            "booking_reason": "reconciliation_changed_before_click",
            "reconcile_fingerprint": pre_fingerprint,
        }

    evidence = inspect_selenium(driver, expected_account, selectors)
    if not evidence.get("refill_eligible"):
        return {
            "booking_status": "BLOCKED",
            "booking_executed": False,
            "booking_reason": evidence.get("refill_reason", "offer_unverified"),
            "reconcile_fingerprint": pre_fingerprint,
        }

    offer = _unique(driver, selectors["refill_offer"])
    button = _unique(driver, selectors["refill_button"], scope=offer)
    if (
        not button.is_enabled()
        or button.get_attribute("aria-disabled") == "true"
        or button.get_attribute("disabled") is not None
        or not any(word in element_label(driver, button).casefold()
                   for word in ("nachbuchen", "buchen", "aktivieren"))
    ):
        return {
            "booking_status": "BLOCKED",
            "booking_executed": False,
            "booking_reason": "button_unverified",
            "reconcile_fingerprint": pre_fingerprint,
        }

    # One click only. No JS fallback, no second submit, no automatic retry.
    button.click()

    try:
        def confirmation_changed(_):
            status, fingerprint = success_snapshot(driver, selectors)
            if status != "SUCCESS":
                return False
            return fingerprint if fingerprint else False

        WebDriverWait(driver, timeout_seconds).until(confirmation_changed)

        # Force a fresh provider view before accepting success.
        driver.refresh()
        WebDriverWait(driver, timeout_seconds).until(protected_session_visible)
        post_status, post_fingerprint = reconciliation_snapshot(
            driver, expected_account, selectors
        )
        if post_status != "SUCCESS" or not post_fingerprint:
            raise BookingUnknownError("post_click_reconciliation_unknown")
        if pre_fingerprint and post_fingerprint == pre_fingerprint:
            raise BookingUnknownError("reconciliation_marker_did_not_change")

        return {
            "booking_status": "SUCCESS",
            "booking_executed": True,
            "booking_reason": "free_one_gb_reconciled",
            "reconcile_fingerprint": post_fingerprint,
        }
    except BookingUnknownError:
        raise
    except Exception as exc:
        raise BookingUnknownError("post_click_outcome_unknown") from exc
