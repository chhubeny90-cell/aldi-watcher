"""Conservative policy for a specifically scoped, free LIDL 1-GB refill.

Selectors must be captured from the authenticated account. No guessed portal
selectors or undocumented API response fields authorize a booking.
"""
import os
import re


SELECTOR_ENV = {
    'active_tariff': 'LIDL_ACTIVE_TARIFF_SELECTOR',
    'refill_offer': 'LIDL_REFILL_OFFER_SELECTOR',
    'refill_button': 'LIDL_REFILL_BUTTON_SELECTOR',
    'refill_success': 'LIDL_REFILL_SUCCESS_SELECTOR',
}


def configured_selectors():
    return {key: os.getenv(env, '').strip() for key, env in SELECTOR_ENV.items()}


def unavailable(reason):
    return {'refill_eligible': False, 'refill_type': 'UNKNOWN',
            'refill_reason': reason}


def assess_refill(tariff, offer, button, enabled):
    """Only a unique offer in an authenticated account can reach this policy."""
    tariff, offer, button = (' '.join(value.split()) for value in (tariff, offer, button))
    if not re.fullmatch(r'(?:LIDL Connect )?Unlimited on Demand [SML]', tariff, re.I):
        return unavailable('active_tariff_unverified')
    quantities = re.findall(r'(?<![\d.,])([\d]+(?:[.,]\d+)?)\s*GB\b', offer, re.I)
    if not quantities or any(q not in {'1', '1.0', '1,0', '1.00', '1,00'} for q in quantities):
        return unavailable('not_exactly_one_gb')
    if not re.search(r'\bUnlimited\b', offer, re.I) or not re.search(r'\b(?:Refill|Nachbuch\w*)\b', offer, re.I):
        return unavailable('not_unlimited_refill')
    prices = re.findall(r'(?<![\d.,])([\d]+(?:[.,]\d{1,2})?)\s*(?:€|EUR\b)', offer, re.I)
    if any(float(price.replace(',', '.')) != 0 for price in prices):
        return unavailable('paid_option')
    if not prices and not re.search(r'\bkostenlos\b', offer, re.I):
        return unavailable('price_unverified')
    if re.search(r'\b(?:nicht kostenlos|kostenpflichtig|monatlich|Abo|automatische Verlängerung)\b', offer, re.I):
        return unavailable('conflicting_terms')
    if not re.search(r'\b(?:nachbuchen|buchen|Refill)\b', button, re.I):
        return unavailable('button_unverified')
    if enabled is not True:
        return unavailable('button_disabled')
    return {'refill_eligible': True, 'refill_type': 'FREE_UNLIMITED',
            'refill_reason': 'free_one_gb_button_available'}


def inspect_selenium(driver, selectors=None):
    """Read availability without clicking; never return raw account text."""
    from selenium.webdriver.common.by import By
    from monitoring import session_visible, require_origin
    selectors = configured_selectors() if selectors is None else selectors
    if not all(selectors.get(key) for key in ('active_tariff', 'refill_offer', 'refill_button')):
        return unavailable('selectors_unconfigured')
    try:
        require_origin(driver, 'https://kundenkonto.lidl-connect.de/')
        if not session_visible(driver):
            return unavailable('session_unverified')
        def unique(root, selector):
            elements = root.find_elements(By.CSS_SELECTOR, selector)
            if len(elements) != 1 or not elements[0].is_displayed():
                raise ValueError('ambiguous_or_hidden_element')
            return elements[0]
        tariff = unique(driver, selectors['active_tariff'])
        offer = unique(driver, selectors['refill_offer'])
        button = unique(offer, selectors['refill_button'])
        enabled = (button.is_enabled() and button.get_attribute('aria-disabled') != 'true'
                   and button.get_attribute('disabled') is None)
        return assess_refill(tariff.text, offer.text, button.text, enabled)
    except Exception:
        return unavailable('offer_unverified')
