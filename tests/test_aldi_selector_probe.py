from unittest.mock import MagicMock, patch

from core.aldi_selector_probe import probe_selectors, sanitized_probe


ACCOUNT = '0152 00000000'


def _element(**attrs):
    element = MagicMock()
    element.get_attribute.side_effect = lambda name: attrs.get(name)
    return element


def test_sanitized_probe_rejects_identifier_like_values():
    raw = {
        'account': {
            'candidates': ['[id="accountCard"]', '[id="account123456789"]'],
        },
        'refill_button': {
            'candidates': ['[data-testid="refillButton"]'],
        },
    }
    clean = sanitized_probe(raw)
    assert clean['account']['candidates'] == ['[id="accountCard"]']
    assert clean['account']['unique'] == '[id="accountCard"]'
    assert clean['refill_button']['unique'] == '[data-testid="refillButton"]'


def test_probe_finds_only_structural_candidates_and_never_clicks():
    driver = MagicMock()
    driver.current_url = 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'

    account = _element(id='accountCard')
    tariff = _element(**{'data-testid': 'activeTariff'})
    offer = _element(id='freeRefill')
    success = _element(id='lastRefill')
    button = _element(**{'data-testid': 'refillButton'})

    texts = {
        account: ACCOUNT,
        tariff: 'Jahres-Paket S',
        offer: '1 GB Datenvolumen kostenlos nachbuchen',
        success: '1 GB erfolgreich nachgebucht',
    }

    def visible(_driver, selector, scope=None):
        assert scope is None
        if selector == '*':
            return [account, tariff, offer, success]
        if selector == "button,a,[role='button'],input[type='submit']":
            return [button]
        by_selector = {
            '[id="accountCard"]': [account],
            '[data-testid="activeTariff"]': [tariff],
            '[id="freeRefill"]': [offer],
            '[id="lastRefill"]': [success],
            '[data-testid="refillButton"]': [button],
        }
        return by_selector.get(selector, [])

    with patch('core.aldi_selector_probe.protected_session_visible', return_value=True), \
         patch('core.aldi_selector_probe.find_visible_elements', side_effect=visible), \
         patch('core.aldi_selector_probe.rendered_text', side_effect=lambda _d, e: texts[e]), \
         patch('core.aldi_selector_probe.element_label', return_value='1 GB nachbuchen'):
        result = probe_selectors(driver, ACCOUNT)

    assert result['account']['unique'] == '[id="accountCard"]'
    assert result['active_tariff']['unique'] == '[data-testid="activeTariff"]'
    assert result['refill_offer']['unique'] == '[id="freeRefill"]'
    assert result['refill_button']['unique'] == '[data-testid="refillButton"]'
    assert result['refill_success']['unique'] == '[id="lastRefill"]'
    assert result['refill_reconcile']['unique'] == '[id="lastRefill"]'
    button.click.assert_not_called()


def test_wrong_origin_returns_empty_probe():
    driver = MagicMock()
    driver.current_url = 'https://attacker.invalid/'
    result = probe_selectors(driver, ACCOUNT)
    assert all(item['count'] == 0 for item in result.values())
