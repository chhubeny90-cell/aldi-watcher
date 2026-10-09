"""Evidence-gated ALDI TALK free 1-GB refill helpers.

Read-only inspection and live booking share exactly the same account/offer
validation. Live booking is intentionally separate and requires explicit
selectors captured from authenticated provider markup. No endpoint is guessed.
"""
import os
import re

from plugins.base_watcher import RechargeUnknownError


SELECTOR_ENV = {
    'account': 'ALDI_ACCOUNT_SELECTOR',
    'active_tariff': 'ALDI_ACTIVE_TARIFF_SELECTOR',
    'refill_offer': 'ALDI_REFILL_OFFER_SELECTOR',
    'refill_button': 'ALDI_REFILL_BUTTON_SELECTOR',
    'refill_success': 'ALDI_REFILL_SUCCESS_SELECTOR',
    'refill_reconcile': 'ALDI_REFILL_RECONCILE_SELECTOR',
}

_ONE_GB = {'1', '1.0', '1,0', '1.00', '1,00'}
_SUCCESS_WORDS = re.compile(r'\b(?:erfolgreich|nachgebucht|gebucht|aktiviert|gutgeschrieben)\b', re.I)
_NEGATIVE_WORDS = re.compile(r'\b(?:nicht|fehlgeschlagen|fehler|abgebrochen|storniert)\b', re.I)


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
    if not quantities or any(quantity not in _ONE_GB for quantity in quantities):
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


def _unique(driver, selector, scope=None):
    from browser_dom import find_visible_elements
    elements = find_visible_elements(driver, selector, scope=scope)
    if len(elements) != 1:
        raise ValueError('ambiguous_or_hidden_element')
    return elements[0]


def _button_enabled(button):
    return (
        button.is_enabled()
        and button.get_attribute('aria-disabled') != 'true'
        and button.get_attribute('disabled') is None
    )


def _account_matches(driver, expected_account, selector):
    from browser_dom import rendered_text
    observed = normalize_msisdn(rendered_text(driver, _unique(driver, selector)))
    expected = normalize_msisdn(expected_account)
    return bool(expected and observed and expected == observed)


def _success_text_ok(text):
    text = ' '.join((text or '').split())
    quantities = re.findall(r'(?<![\d.,])(\d+(?:[.,]\d+)?)\s*GB\b', text, re.I)
    return bool(
        quantities
        and all(quantity in _ONE_GB for quantity in quantities)
        and _SUCCESS_WORDS.search(text)
        and not _NEGATIVE_WORDS.search(text)
    )


def inspect_selenium(driver, expected_account, selectors=None):
    """Inspect authenticated ALDI markup without clicking or returning raw text."""
    from browser_dom import rendered_text, element_label
    from monitoring import session_visible, require_origin

    selectors = configured_selectors() if selectors is None else selectors
    required = ('account', 'active_tariff', 'refill_offer', 'refill_button')
    if not all(selectors.get(key) for key in required):
        return unavailable('selectors_unconfigured')

    try:
        require_origin(driver, 'https://www.alditalk-kundenportal.de/')
        if not session_visible(driver):
            return unavailable('session_unverified')

        account = _unique(driver, selectors['account'])
        tariff = _unique(driver, selectors['active_tariff'])
        offer = _unique(driver, selectors['refill_offer'])
        button = _unique(driver, selectors['refill_button'], scope=offer)
        return assess_refill(
            rendered_text(driver, account),
            expected_account,
            rendered_text(driver, tariff),
            rendered_text(driver, offer),
            element_label(driver, button),
            _button_enabled(button),
        )
    except Exception:
        return unavailable('offer_unverified')


def book_selenium(driver, expected_account, selectors=None, timeout_seconds=15):
    """Click exactly once after a fresh evidence check and require a new success notice.

    Any exception after the click is UNKNOWN: the caller must persist the lock and
    reconcile before another booking attempt.
    """
    from browser_dom import rendered_text
    from monitoring import session_visible, require_origin
    from selenium.webdriver.support.ui import WebDriverWait

    selectors = configured_selectors() if selectors is None else selectors
    required = ('account', 'active_tariff', 'refill_offer', 'refill_button', 'refill_success')
    if not all(selectors.get(key) for key in required):
        return False

    evidence = inspect_selenium(driver, expected_account, selectors)
    if not (
        evidence.get('account_verified') is True
        and evidence.get('refill_eligible') is True
        and evidence.get('refill_type') == 'FREE_ONE_GB'
    ):
        return False

    require_origin(driver, 'https://www.alditalk-kundenportal.de/')
    if not session_visible(driver) or not _account_matches(driver, expected_account, selectors['account']):
        return False

    # An already-visible success notice cannot prove this new request.
    old_success = []
    try:
        from browser_dom import find_visible_elements
        old_success = find_visible_elements(driver, selectors['refill_success'])
    except Exception:
        return False
    if old_success:
        return False

    offer = _unique(driver, selectors['refill_offer'])
    button = _unique(driver, selectors['refill_button'], scope=offer)
    if not _button_enabled(button):
        return False

    clicked = False
    try:
        button.click()
        clicked = True
        success = WebDriverWait(driver, timeout_seconds).until(
            lambda _: (_unique(driver, selectors['refill_success'])
                       if len(__import__('browser_dom').find_visible_elements(driver, selectors['refill_success'])) == 1
                       else False)
        )
        require_origin(driver, 'https://www.alditalk-kundenportal.de/')
        if not session_visible(driver):
            raise RechargeUnknownError('ALDI session lost after booking action')
        if not _account_matches(driver, expected_account, selectors['account']):
            raise RechargeUnknownError('ALDI account changed after booking action')
        if not _success_text_ok(rendered_text(driver, success)):
            raise RechargeUnknownError('ALDI success notice is not specific to a successful 1-GB refill')
        return True
    except RechargeUnknownError:
        raise
    except Exception:
        if clicked:
            raise RechargeUnknownError('ALDI browser booking outcome is unknown') from None
        return False


def reconcile_selenium(driver, expected_account, selectors=None):
    """Read a provider-side persistent reconciliation marker without clicking.

    Returns SUCCESS only for an account-scoped, explicit successful 1-GB marker.
    Anything else remains UNKNOWN and therefore blocks retries.
    """
    from browser_dom import rendered_text
    from monitoring import session_visible, require_origin

    selectors = configured_selectors() if selectors is None else selectors
    if not selectors.get('account') or not selectors.get('refill_reconcile'):
        return 'UNKNOWN'
    try:
        require_origin(driver, 'https://www.alditalk-kundenportal.de/')
        if not session_visible(driver):
            return 'UNKNOWN'
        if not _account_matches(driver, expected_account, selectors['account']):
            return 'UNKNOWN'
        marker = _unique(driver, selectors['refill_reconcile'])
        return 'SUCCESS' if _success_text_ok(rendered_text(driver, marker)) else 'UNKNOWN'
    except Exception:
        return 'UNKNOWN'
