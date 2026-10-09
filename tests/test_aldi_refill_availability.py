from unittest.mock import MagicMock, patch

import pytest

from core.aldi_refill import assess_refill, inspect_selenium, normalize_msisdn


ACCOUNT = '0152 00000000'
OFFER = '1 GB Datenvolumen nachbuchen kostenlos 0,00 €'
SELECTORS = {
    'account': '.account',
    'active_tariff': '.tariff',
    'refill_offer': '.offer',
    'refill_button': '.refill',
    'refill_success': '.success',
}


@pytest.mark.parametrize('value,expected', [
    ('0152 00000000', '015200000000'),
    ('+49 152 00000000', '015200000000'),
    ('0049 152 00000000', '015200000000'),
    ('masked-2640', ''),
])
def test_normalize_msisdn_requires_full_number(value, expected):
    assert normalize_msisdn(value) == expected


@pytest.mark.parametrize('account,tariff,offer,button,enabled,reason', [
    (ACCOUNT, 'Jahres-Paket', OFFER, '1 GB nachbuchen', True, 'free_one_gb_offer_available'),
    ('0152 11111111', 'Jahres-Paket', OFFER, '1 GB nachbuchen', True, 'account_mismatch'),
    (ACCOUNT, '', OFFER, '1 GB nachbuchen', True, 'active_tariff_unverified'),
    (ACCOUNT, 'Jahres-Paket', OFFER.replace('1 GB', '2 GB'), '1 GB nachbuchen', True, 'not_exactly_one_gb'),
    (ACCOUNT, 'Jahres-Paket', '1 GB Datenvolumen nachbuchen 2,99 €', '1 GB nachbuchen', True, 'paid_option'),
    (ACCOUNT, 'Jahres-Paket', '1 GB Datenvolumen nachbuchen', '1 GB nachbuchen', True, 'price_unverified'),
    (ACCOUNT, 'Jahres-Paket', OFFER + ' kostenpflichtig', '1 GB nachbuchen', True, 'conflicting_terms'),
    (ACCOUNT, 'Jahres-Paket', OFFER, 'Tarif wechseln', True, 'button_unverified'),
    (ACCOUNT, 'Jahres-Paket', OFFER, '1 GB nachbuchen', False, 'button_disabled'),
])
def test_only_exact_free_one_gb_offer_is_eligible(account, tariff, offer, button, enabled, reason):
    result = assess_refill(account, ACCOUNT, tariff, offer, button, enabled)
    assert result['refill_reason'] == reason
    assert result['refill_eligible'] is (reason == 'free_one_gb_offer_available')


def test_unconfigured_selectors_do_not_touch_driver():
    driver = MagicMock()
    result = inspect_selenium(driver, ACCOUNT, {})
    assert result['refill_reason'] == 'selectors_unconfigured'
    driver.execute_script.assert_not_called()
    driver.find_elements.assert_not_called()


def test_authenticated_inspection_is_read_only_and_account_scoped():
    driver = MagicMock()
    driver.current_url = 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'
    account, tariff, offer, button = (MagicMock() for _ in range(4))
    button.is_enabled.return_value = True
    button.get_attribute.return_value = None

    def find(_driver, selector, scope=None):
        assert _driver is driver
        if selector == '.account':
            return [account]
        if selector == '.tariff':
            return [tariff]
        if selector == '.offer':
            return [offer]
        if selector == '.refill' and scope is offer:
            return [button]
        return []

    text = {account: ACCOUNT, tariff: 'Jahres-Paket', offer: OFFER}
    with patch('monitoring.session_visible', return_value=True), \
         patch('browser_dom.find_visible_elements', side_effect=find), \
         patch('browser_dom.rendered_text', side_effect=lambda _driver, element: text[element]), \
         patch('browser_dom.element_label', return_value='1 GB nachbuchen'):
        result = inspect_selenium(driver, ACCOUNT, SELECTORS)

    assert result == {
        'refill_eligible': True,
        'refill_type': 'FREE_ONE_GB',
        'refill_reason': 'free_one_gb_offer_available',
        'account_verified': True,
    }
    button.click.assert_not_called()


def test_wrong_origin_fails_closed_without_click():
    driver = MagicMock()
    driver.current_url = 'https://attacker.invalid/'
    button = MagicMock()
    with patch('monitoring.session_visible', return_value=True):
        result = inspect_selenium(driver, ACCOUNT, SELECTORS)
    assert not result['refill_eligible']
    assert result['refill_reason'] == 'offer_unverified'
    button.click.assert_not_called()
