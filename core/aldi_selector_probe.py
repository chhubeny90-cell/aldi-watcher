"""Read-only selector discovery for the authenticated ALDI portal.

The probe classifies elements in memory and returns only structural CSS selectors
built from non-sensitive attributes. It never returns rendered text, account
numbers, cookies, tokens, URLs, or form values and it never clicks anything.
"""

import re

from browser_dom import element_label, find_visible_elements, rendered_text
from core.aldi_refill import normalize_msisdn, protected_session_visible
from monitoring import require_origin


_ROLES = (
    "account",
    "active_tariff",
    "refill_offer",
    "refill_button",
    "refill_success",
    "refill_reconcile",
)
_SAFE_ATTRS = ("data-testid", "data-test", "data-qa", "id", "name")
_SAFE_VALUE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
_LONG_DIGITS = re.compile(r"(?:\d[^\d]*){6,}")
_ONE_GB = re.compile(r"(?<![\d.,])1(?:[.,]0{1,2})?\s*GB\b", re.I)
_FREE = re.compile(r"(?:\bkostenlos\b|(?<![\d.,])0(?:[.,]0{1,2})?\s*(?:€|EUR\b))", re.I)
_BOOK = re.compile(r"\b(?:nachbuchen|buchen|aktivieren)\b", re.I)
_SUCCESS = re.compile(r"\b(?:erfolgreich|nachgebucht|gebucht|aktiviert|gutgeschrieben)\b", re.I)
_TARIFF = re.compile(r"\b(?:tarif|paket|option)\b", re.I)


def _attribute_selector(driver, element):
    for attr in _SAFE_ATTRS:
        try:
            value = (element.get_attribute(attr) or "").strip()
        except Exception:
            continue
        if not _SAFE_VALUE.fullmatch(value):
            continue
        if "@" in value or _LONG_DIGITS.search(value):
            continue
        selector = f'[{attr}="{value}"]'
        try:
            if len(find_visible_elements(driver, selector)) == 1:
                return selector
        except Exception:
            continue
    return None


def _add(result, role, selector):
    if not selector:
        return
    values = result[role]["candidates"]
    if selector not in values and len(values) < 5:
        values.append(selector)


def _safe_text(driver, element):
    try:
        return " ".join(rendered_text(driver, element).split())
    except Exception:
        return ""


def probe_selectors(driver, expected_account):
    result = {role: {"count": 0, "candidates": [], "unique": None} for role in _ROLES}
    try:
        require_origin(driver, "https://www.alditalk-kundenportal.de/")
        if not protected_session_visible(driver):
            return result
        expected = normalize_msisdn(expected_account)
        if not expected:
            return result

        for element in find_visible_elements(driver, "*"):
            text = _safe_text(driver, element)
            if not text or len(text) > 400:
                continue
            selector = _attribute_selector(driver, element)
            if not selector:
                continue

            normalized = normalize_msisdn(text)
            if normalized and normalized == expected:
                _add(result, "account", selector)

            if _TARIFF.search(text) and not _ONE_GB.search(text) and len(text) <= 160:
                _add(result, "active_tariff", selector)

            if _ONE_GB.search(text) and _FREE.search(text) and _BOOK.search(text):
                _add(result, "refill_offer", selector)

            if _ONE_GB.search(text) and _SUCCESS.search(text):
                _add(result, "refill_success", selector)
                _add(result, "refill_reconcile", selector)

        for control in find_visible_elements(
            driver, "button,a,[role='button'],input[type='submit']"
        ):
            try:
                label = element_label(driver, control)
            except Exception:
                label = ""
            if not _BOOK.search(label or ""):
                continue
            selector = _attribute_selector(driver, control)
            _add(result, "refill_button", selector)

        for role in _ROLES:
            candidates = result[role]["candidates"]
            result[role]["count"] = len(candidates)
            result[role]["unique"] = candidates[0] if len(candidates) == 1 else None
        return result
    except Exception:
        return result


def sanitized_probe(probe):
    clean = {}
    if not isinstance(probe, dict):
        return clean
    selector_pattern = re.compile(
        r'^\[(?:data-testid|data-test|data-qa|id|name)="[A-Za-z][A-Za-z0-9_.:-]{0,79}"\]$'
    )
    for role in _ROLES:
        item = probe.get(role, {})
        if not isinstance(item, dict):
            item = {}
        candidates = [
            value for value in item.get("candidates", [])[:5]
            if isinstance(value, str) and selector_pattern.fullmatch(value)
            and not _LONG_DIGITS.search(value)
        ]
        clean[role] = {
            "count": len(candidates),
            "candidates": candidates,
            "unique": candidates[0] if len(candidates) == 1 else None,
        }
    return clean
