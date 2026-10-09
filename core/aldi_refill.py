"""Read-only evidence for the ALDI TALK free 1-GB refill.

No selector is guessed and this module never clicks a control. A refill becomes
eligible only when an authenticated account exposes uniquely scoped account,
tariff, offer and action elements configured from observed provider markup.
"""
import os
import re


SELECTOR_ENV = {
    'account': 'ALDI_ACCOUNT_SELECTOR',
    'active_tariff': 'ALDI_ACTIVE_TARIFF_SELECTOR',
    'refill_offer': 'ALDI_REFILL_OFFER_SELECTOR',
    'refill_button': 'ALDI_REFILL_BUTTON_SELECTOR',
    'refill_success': 'ALDI_REFILL_SUCCESS_SELECTOR',
}


def configured_selectors():
    return {key: os.getenv(env, '').strip() for key, env in SELECTOR_ENV.items()}


def unavailable(reason, account_verified=False):
    return {
        'refill_eligible': False,
        'refill_type': 'UNKNOWN',
        'refill_reason': reason,
        'account_verified': bool(account_verified),
    }


def normalize_msisdn(value):
    """Normalize a German mobile number for exact in-memory comparison."""
    digits = ''.join(re.findall(r'\d', value or ''))
    if digits.startswith('0049'):
        digits = '0' + digits[4:]
    elif digits.startswith('49') and len(digits) >= 11:
        digits = '0' + digits[2:]
    return digits if 10 <= len(digits) <= 15 else ''


def assess_refill(account, expected_account, tariff, offer, button, enabled):
    """Accept only an exact account match and an explicit free 1-GB offer."""
    expected = normalize_msisdn(expected_account)
    observed = normalize_msisdn(account)
    if not expected or not observed:
        return unavailable('account_unverified')
    if observed != expected:
        return unavailable('account_mismatch')

    tariff = ' '.join((tariff or '').split())
    offer = ' '.join((offer or '').split())
    button = ' '.join((button or '').split())
    if not tariff:
        return unavailable('active_tariff_unverified', True)

    quantities = re.findall(r'(?<![\d.,])(\d+(?:[.,]\d+)?)\s*GB\b', offer, re.I)
    accepted_one_gb = {'1', '1.0', '1,0', '1.00', '1,00'}
    if not quantities or any(quantity not in accepted_one_gb for quantity in quantities):
        return unavailable('not_exactly_one_gb', True)

    if not re.search(r'\b(?:nachbuch\w*|zusatz\w*|extra|datenoption)\b', offer, re.I):
        return unavailable('offer_unverified', True)

    prices = re.findall(r'(?<![\d.,])(\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR\b)', offer, re.I)
    if any(float(price.replace(',', '.')) != 0 for price in prices):
        return unavailable('paid_option', True)
    if not prices and not re.search(r'\bkostenlos\b', offer, re.I):
        return unavailable('price_unverified', True)
    if re.search(r'\b(?:nicht kostenlos|kostenpflichtig|abo|automatische verlängerung)\b', offer, re.I):
        return unavailable('conflicting_terms', True)

    if not re.search(r'\b(?:nachbuchen|buchen|aktivieren)\b', button, re.I):
        return unavailable('button_unverified', True)
    if enabled is not True:
        return unavailable('button_disabled', True)

    return {
        'refill_eligible': True,
        'refill_type': 'FREE_ONE_GB',
        'refill_reason': 'free_one_gb_offer_available',
        'account_verified': True,
    }


def inspect_selenium(driver, expected_account, selectors=None):
    """Inspect authenticated ALDI markup without clicking or returning raw text."""
    from browser_dom import find_visible_elements, rendered_text, element_label
    from monitoring import session_visible, require_origin

    selectors = configured_selectors() if selectors is None else selectors
    required = ('account', 'active_tariff', 'refill_offer', 'refill_button')
    if not all(selectors.get(key) for key in required):
        return unavailable('selectors_unconfigured')

    try:
        require_origin(driver, 'https://www.alditalk-kundenportal.de/')
        if not session_visible(driver):
            return unavailable('session_unverified')

        def unique(selector, scope=None):
            elements = find_visible_elements(driver, selector, scope=scope)
            if len(elements) != 1:
                raise ValueError('ambiguous_or_hidden_element')
            return elements[0]

        account = unique(selectors['account'])
        tariff = unique(selectors['active_tariff'])
        offer = unique(selectors['refill_offer'])
        button = unique(selectors['refill_button'], scope=offer)
        enabled = (
            button.is_enabled()
            and button.get_attribute('aria-disabled') != 'true'
            and button.get_attribute('disabled') is None
        )
        return assess_refill(
            rendered_text(driver, account),
            expected_account,
            rendered_text(driver, tariff),
            rendered_text(driver, offer),
            element_label(driver, button),
            enabled,
        )
    except Exception:
        return unavailable('offer_unverified')
