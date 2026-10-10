"""Fail-closed detection for ALDI TALK's repeated free 1-GB refill.

The detector works only inside an already authenticated ALDI customer-area
session. It never clicks by itself. A live caller receives a control only when
all of these are simultaneously proven from the rendered page:
- remaining high-speed volume is at most 1 GB,
- the authenticated page identifies a verified eligible tariff/context,
- exactly one enabled refill control is associated with exactly 1 GB,
- that local offer is explicitly free/0 EUR and contains no positive price.

Only an explicitly identified active Unlimited tariff is eligible. Ordinary
Tarif S/M/L names, Jahres-Paket/Jahrestarif and Basis-Tarif are not sufficient.
Generic refill hints elsewhere on the page do not prove tariff eligibility.
"""

import math
import re


PORTAL_URL = "https://www.alditalk-kundenportal.de/portal/auth/uebersicht/"


def unavailable(reason):
    return {
        "refill_eligible": False,
        "refill_type": "UNKNOWN",
        "refill_reason": reason,
        "refill_candidate_count": 0,
    }


def _normalise(value):
    return " ".join((value or "").split())


def _eligible_tariff(active_tariff_text):
    """Require an explicit Unlimited tariff identity; reject annual/base plans.

    This is a conservative booking gate, not a claim about every ALDI product.
    The caller must supply tariff headings, never generic marketing/body text.
    """
    if re.search(r"\b(?:Jahres[\s-]*(?:paket|tarif)|Basis[\s-]*Tarif)\b",
                 active_tariff_text, re.I):
        return None
    identities = []
    for line in active_tariff_text.splitlines():
        line = _normalise(line)
        match = re.fullmatch(
            r"(?:ALDI\s+TALK\s+)?"
            r"(?:(?:Tarif\s+)?[SML]\s*[-–:]?\s+Unlimited"
            r"|Unlimited(?:\s+(?:Tarif\s+)?[SML])?"
            r"|Tarif\s+Unlimited(?:\s+[SML])?"
            r"|Tarif\s+[SML]\s*[-–:]?\s+Unlimited"
            r"|Unlimited\s+GB\s+nachbuchen(?:\s*[-–:]?\s+Tarif\s+[SML])?)",
            line, re.I,
        )
        if match:
            identities.append(line)
    # Refill-section headings (for example, "Unlimited GB nachbuchen") are\n    # offers, not tariff identities, and are deliberately not accepted here.\n    # A single active identity is required. Multiple products are ambiguous.
    return "UNLIMITED" if len(identities) == 1 else None


def _exact_one_gb(text):
    quantities = re.findall(r"(?<![\d.,])([\d]+(?:[.,]\d+)?)\s*GB\b", text, re.I)
    if not quantities:
        return False
    return all(q.replace(",", ".") in {"1", "1.0", "1.00"} for q in quantities)


def _free_price(text):
    prices = re.findall(r"(?<![\d.,])([\d]+(?:[.,]\d{1,2})?)\s*(?:€|EUR\b)", text, re.I)
    if any(float(price.replace(",", ".")) > 0 for price in prices):
        return False
    return bool(prices) or bool(re.search(r"\bkostenlos\b", text, re.I))


def assess_refill(page_text, offer_text, button_text, enabled, candidate_count, remaining_gb,
                  active_tariff_text=None):
    # Pure callers may supply a tariff identity as page_text. Live DOM callers
    # must pass visible tariff headings separately from the rest of the page.
    tariff_text = page_text if active_tariff_text is None else active_tariff_text
    tariff_text = tariff_text or ""
    offer_text = _normalise(offer_text)
    button_text = _normalise(button_text)

    if isinstance(remaining_gb, bool) or not isinstance(remaining_gb, (int, float)):
        return unavailable("remaining_volume_unverified")
    if not math.isfinite(remaining_gb) or remaining_gb < 0:
        return unavailable("remaining_volume_unverified")
    # The exact portal offer remains the final gate. Allow the contract boundary
    # of 1.00 GB, but no value above it.
    if remaining_gb > 1.0:
        return unavailable("remaining_volume_above_one_gb")

    tariff = _eligible_tariff(tariff_text)
    if tariff is None:
        return unavailable("active_tariff_unverified")

    if candidate_count != 1:
        result = unavailable("refill_control_ambiguous")
        result["refill_candidate_count"] = int(candidate_count)
        return result
    if not _exact_one_gb(offer_text):
        return unavailable("not_exactly_one_gb")
    if not re.search(r"\b(?:nachbuchen|nachbuchung|buchen|highspeed|datenvolumen)\b", offer_text, re.I):
        return unavailable("not_refill_offer")
    if not _free_price(offer_text):
        return unavailable("price_unverified_or_paid")
    if re.search(r"\b(?:kostenpflichtig|monatlich|abo|automatische verlängerung|automatische verlaengerung)\b", offer_text, re.I):
        return unavailable("conflicting_terms")
    if not re.search(r"\b(?:nachbuchen|buchen|weiter|bestätigen|bestaetigen)\b", button_text, re.I):
        return unavailable("button_unverified")
    if enabled is not True:
        return unavailable("button_disabled")

    return {
        "refill_eligible": True,
        # Keep the existing stable type for compatibility with the old provider
        # guard; tariff_evidence distinguishes the verified portal context.
        "refill_type": "FREE_UNLIMITED",
        "refill_reason": "free_one_gb_button_available",
        "refill_candidate_count": 1,
        "tariff_evidence": tariff,
    }


def _composed_parent(driver, element):
    return driver.execute_script(
        """
        const el = arguments[0];
        if (!el) return null;
        if (el.assignedSlot) return el.assignedSlot;
        if (el.parentElement) return el.parentElement;
        const root = el.getRootNode && el.getRootNode();
        return root && root.host ? root.host : null;
        """,
        element,
    )


def _offer_context(driver, control):
    from browser_dom import rendered_text

    current = control
    best = ""
    for _ in range(8):
        try:
            text = rendered_text(driver, current)
        except Exception:
            text = ""
        if text:
            best = text
            if (re.search(r"(?<![\d.,])1(?:[.,]0+)?\s*GB\b", text, re.I)
                    and re.search(r"\b(?:nachbuch\w*|kostenlos|highspeed|datenvolumen)\b", text, re.I)):
                return text
        try:
            current = _composed_parent(driver, current)
        except Exception:
            break
        if current is None:
            break
    return best


def locate_selenium(driver, remaining_gb):
    """Return (sanitized evidence, WebElement-or-None) without clicking."""
    from browser_dom import element_label, find_visible_elements, rendered_text
    from monitoring import require_origin
    import watcher

    try:
        require_origin(driver, PORTAL_URL)
        if not watcher.aldi_session_visible(driver):
            return unavailable("session_unverified"), None
        page_text = rendered_text(driver)
        tariff_headings = []
        for heading in find_visible_elements(driver, "h1,h2,h3,h4,h5,h6,[role='heading']"):
            text = rendered_text(driver, heading)
            if re.search(r"\b(?:tarif|unlimited|jahres[\s-]*paket)\b", text, re.I):
                tariff_headings.append(text)
        active_tariff_text = "\n".join(tariff_headings)
        if _eligible_tariff(active_tariff_text) is None:
            return unavailable("active_tariff_unverified"), None
        candidates = []
        for control in find_visible_elements(driver, "button,a,[role='button'],input[type='submit']"):
            try:
                label = element_label(driver, control)
                context = _offer_context(driver, control)
                combined = f"{label} {context}"
                refillish = bool(re.search(r"\b(?:nachbuch\w*|buchen)\b", combined, re.I))
                one_gb = bool(re.search(r"(?<![\d.,])1(?:[.,]0+)?\s*GB\b", combined, re.I))
                if refillish and one_gb:
                    candidates.append((control, context, label))
            except Exception:
                continue

        if len(candidates) != 1:
            result = unavailable("refill_control_ambiguous")
            result["refill_candidate_count"] = len(candidates)
            return result, None

        control, context, label = candidates[0]
        enabled = (control.is_enabled()
                   and control.get_attribute("aria-disabled") != "true"
                   and control.get_attribute("disabled") is None)
        result = assess_refill(page_text, context, label, enabled, 1, remaining_gb,
                               active_tariff_text=active_tariff_text)
        return result, control if result["refill_eligible"] else None
    except Exception:
        return unavailable("offer_unverified"), None


def inspect_selenium(driver, remaining_gb):
    result, _ = locate_selenium(driver, remaining_gb)
    return result
