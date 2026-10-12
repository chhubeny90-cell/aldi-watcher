"""Fail-closed detection for ALDI TALK's repeated free 1-GB refill.

The detector works only inside an already authenticated ALDI customer-area
session. It never clicks by itself. A live caller receives a control only when
all of these are simultaneously proven from the rendered page:
- remaining high-speed volume is less than 1 GB,
- the authenticated page identifies a verified eligible tariff/context,
- exactly one enabled refill control is associated with exactly 1 GB,
- no positive, conflicting, or unparsed local price is present.

Current ALDI TALK Tarif S/M/L products include the repeated free 1-GB refill.
A verified current S/M/L or legacy Unlimited tariff may therefore use the
published tariff entitlement when the local exact 1-GB refill control carries
no price label. Explicit positive or malformed prices remain blocked.
Jahres-Paket/Jahrestarif and Basis-Tarif remain blocked.
"""

import base64
import hashlib
import json
import math
import re
from urllib.parse import urlencode, urlsplit

from core.aldi_http_login import NAVIGATION, LoginError, phone_identifier, trusted_url


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
    """Require one explicit active current S/M/L or legacy Unlimited identity."""
    if re.search(r"\b(?:Jahres[\s-]*(?:paket|tarif)|Basis[\s-]*Tarif)\b",
                 active_tariff_text, re.I):
        return None
    identities = []
    for line in active_tariff_text.splitlines():
        line = _normalise(line)
        unlimited = re.fullmatch(
            r"(?:ALDI\s+TALK\s+)?"
            r"(?:(?:Tarif\s+)?[SML]\s*[-–:]?\s+Unlimited"
            r"|Unlimited(?:\s+(?:Tarif\s+)?[SML])?"
            r"|Tarif\s+Unlimited(?:\s+[SML])?"
            r"|Tarif\s+[SML]\s*[-–:]?\s+Unlimited"
            r")",
            line, re.I,
        )
        current_sml = re.fullmatch(r"(?:ALDI\s+TALK\s+)?Tarif\s+[SML]", line, re.I)
        if unlimited:
            identities.append("UNLIMITED")
        elif current_sml:
            identities.append("CURRENT_SML")
    return identities[0] if len(identities) == 1 else None


def _exact_one_gb(text):
    if re.search(r"[-−]\s*\d[\d.,]*\s*(?:GB|MB|TB|KB|GiB|MiB|TiB|KiB)\b", text, re.I):
        return False
    quantities = re.findall(r"(?<![\w.,+\-−])([+\-]?[\d][\d.,]*)\s*GB\b", text, re.I)
    mentions = re.findall(r"(?<![A-Za-z])(?:GB|MB|TB|KB|GiB|MiB|TiB|KiB)\b", text, re.I)
    return (bool(quantities) and len(quantities) == len(mentions)
            and all(re.fullmatch(r"\+?1(?:[.,]0{1,2})?", q) for q in quantities))


def _price_state(text):
    """Return FREE, PAID, ABSENT, or UNVERIFIED for the local offer text."""
    if re.search(r"[+\-−]\s*\d[\d.,]*\s*(?:€|EUR\b)", text, re.I):
        return "UNVERIFIED"
    prices = re.findall(r"(?<![\w.,+\-])([+\-]?[\d][\d.,]*)\s*(?:€|EUR\b)", text, re.I)
    mentions = re.findall(r"€|(?<![A-Za-z])EUR\b", text, re.I)
    if mentions:
        if not prices or len(prices) != len(mentions):
            return "UNVERIFIED"
        if any(not re.fullmatch(r"0(?:[.,]0{1,2})?", p) for p in prices):
            return "PAID"
        return "FREE"
    return "ABSENT"


def _free_price(text):
    return _price_state(text) == "FREE"


def _free_offer_evidence(offer_text, tariff):
    """Accept published free entitlement only when no local price conflicts."""
    price_state = _price_state(offer_text)
    if price_state in {"PAID", "UNVERIFIED"}:
        return None
    if price_state == "FREE":
        return "explicit_free_offer"
    if tariff in {"UNLIMITED", "CURRENT_SML"} and price_state == "ABSENT":
        return "official_unlimited_entitlement"
    return None


def _portal_origin(driver):
    from monitoring import require_origin
    trusted_url(driver.current_url)
    require_origin(driver, PORTAL_URL)


def _selected_account(driver, expected_account):
    _portal_origin(driver)
    expected = phone_identifier(expected_account)
    host = urlsplit(PORTAL_URL).hostname
    domains = {host, host.removeprefix('www.')}
    cookies = [cookie.get('value') for cookie in driver.get_cookies()
               if cookie.get('name') == 'lgrs_id'
               and str(cookie.get('domain', '')).lstrip('.') in domains]
    if not cookies or any(not isinstance(value, str) or len(value) > 256 for value in cookies):
        raise RuntimeError('account_cookie_unverified')
    if len(set(cookies)) != 1:
        raise RuntimeError('account_cookie_unverified')
    try:
        encoded = cookies[0] + '=' * (-len(cookies[0]) % 4)
        decoded = base64.b64decode(encoded, validate=True).decode('utf-8')
        if phone_identifier(decoded) != expected:
            raise RuntimeError('account_mismatch')
    except (ValueError, UnicodeDecodeError, LoginError):
        raise RuntimeError('account_cookie_unverified') from None
    return decoded, expected


def verify_account_selenium(driver, expected_account, timeout_seconds=8):
    decoded, expected = _selected_account(driver, expected_account)
    url = NAVIGATION + '?' + urlencode({'msisdn': decoded})
    driver.set_script_timeout(timeout_seconds + 2)
    result = driver.execute_async_script(r"""
        const url = new URL(arguments[0]);
        const timeout = arguments[1];
        const callback = arguments[arguments.length - 1];
        let completed = false;
        const finish = result => {
            if (!completed) { completed = true; clearTimeout(timer); callback(result); }
        };
        const abort = new AbortController();
        const timer = setTimeout(() => {
            abort.abort(); finish({ok: false});
        }, timeout);
        if (location.origin !== url.origin) { finish({ok: false}); return; }
        fetch(url.href, {
            method: 'GET', credentials: 'same-origin', cache: 'no-store',
            redirect: 'error', headers: {'Accept': 'application/json'}, signal: abort.signal
        }).then(async response => {
            if (!response.ok || response.url !== url.href) { finish({ok: false}); return; }
            const body = await response.text();
            if (body.length > 65536) { finish({ok: false}); return; }
            const payload = JSON.parse(body);
            const subscriptions = payload && payload.userDetails && payload.userDetails.subscriptions;
            finish({ok: true, subscriptions});
        }).catch(() => finish({ok: false}));
    """, url, int(timeout_seconds * 1000))
    _, current = _selected_account(driver, expected_account)
    if current != expected or not isinstance(result, dict) or result.get('ok') is not True:
        raise RuntimeError('protected_account_response_unverified')
    subscriptions = result.get('subscriptions')
    if (not isinstance(subscriptions, list) or not subscriptions
            or any(not isinstance(item, dict) or not item for item in subscriptions)):
        raise RuntimeError('protected_account_response_unverified')
    contents = sorted(json.dumps(item, sort_keys=True, separators=(',', ':')) for item in subscriptions)
    signature = json.dumps([expected, contents], separators=(',', ':')).encode()
    return hashlib.sha256(signature).hexdigest()


def tariff_identity_selenium(driver):
    from browser_dom import find_visible_elements, rendered_text
    import watcher
    _portal_origin(driver)
    if not watcher.aldi_session_visible(driver):
        raise RuntimeError('session_unverified')
    headings = [rendered_text(driver, element)
                for element in find_visible_elements(driver, "h1,h2,h3,h4,h5,h6,[role='heading']")]
    text = '\n'.join(headings)
    if _eligible_tariff(text) is None:
        raise RuntimeError('active_tariff_unverified')
    identities = [_normalise(line).casefold() for line in text.splitlines()
                  if _eligible_tariff(line) is not None]
    if len(identities) != 1:
        raise RuntimeError('active_tariff_unverified')
    return hashlib.sha256(identities[0].encode()).hexdigest()


def assess_refill(page_text, offer_text, button_text, enabled, candidate_count, remaining_gb,
                  active_tariff_text=None):
    tariff_text = page_text if active_tariff_text is None else active_tariff_text
    tariff_text = tariff_text or ""
    offer_text = _normalise(offer_text)
    button_text = _normalise(button_text)

    if isinstance(remaining_gb, bool) or not isinstance(remaining_gb, (int, float)):
        return unavailable("remaining_volume_unverified")
    if not math.isfinite(remaining_gb) or remaining_gb < 0:
        return unavailable("remaining_volume_unverified")
    if remaining_gb >= 1.0:
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
    if not re.search(
            r"\b(?:nachbuchen|nachbuchung|buchen|highspeed|datenvolumen)\b"
            r"|(?<![\d.,])\+\s*1\s*GB\b",
            offer_text, re.I):
        return unavailable("not_refill_offer")
    free_evidence = _free_offer_evidence(offer_text, tariff)
    if free_evidence is None:
        return unavailable("price_unverified_or_paid")
    if re.search(r"\b(?:kostenpflichtig|monatlich|abo|automatische verlängerung|automatische verlaengerung)\b", offer_text, re.I):
        return unavailable("conflicting_terms")
    if not re.search(
            r"\b(?:nachbuchen|buchen|weiter|bestätigen|bestaetigen)\b"
            r"|(?<![\d.,])\+\s*1\s*GB\b",
            button_text, re.I):
        return unavailable("button_unverified")
    if enabled is not True:
        return unavailable("button_disabled")

    return {
        "refill_eligible": True,
        "refill_type": "FREE_UNLIMITED",
        "refill_reason": "free_one_gb_button_available",
        "refill_candidate_count": 1,
        "tariff_evidence": tariff,
        "free_evidence": free_evidence,
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
                refillish = bool(re.search(
                    r"\b(?:nachbuch\w*|buchen)\b|(?<![\d.,])\+\s*1\s*GB\b",
                    combined, re.I,
                ))
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
