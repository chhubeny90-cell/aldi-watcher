import base64
from unittest.mock import Mock

import pytest

from core.aldi_refill import (PORTAL_URL, assess_refill, tariff_identity_selenium,
                              verify_account_selenium)


def eligible(**overrides):
    args = dict(
        page_text='ALDI TALK Tarif S Unlimited',
        offer_text='1 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 €',
        button_text='1 GB nachbuchen',
        enabled=True,
        candidate_count=1,
        remaining_gb=0.42,
    )
    args.update(overrides)
    return assess_refill(**args)


def test_free_tarif_s_one_gb_is_eligible():
    result = eligible()
    assert result['refill_eligible'] is True
    assert result['refill_type'] == 'FREE_UNLIMITED'
    assert result['refill_reason'] == 'free_one_gb_button_available'
    assert result['tariff_evidence'] == 'UNLIMITED'


def test_tarif_m_is_supported():
    result = eligible(page_text='ALDI TALK Tarif M Unlimited')
    assert result['refill_eligible'] is True
    assert result['tariff_evidence'] == 'UNLIMITED'


def test_tarif_l_is_supported():
    result = eligible(page_text='ALDI TALK Tarif L Unlimited')
    assert result['refill_eligible'] is True
    assert result['tariff_evidence'] == 'UNLIMITED'


def test_exactly_one_gb_is_not_eligible():
    result = eligible(remaining_gb=1.0)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'remaining_volume_above_one_gb'


def test_volume_above_one_gb_is_rejected():
    result = eligible(remaining_gb=1.001)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'remaining_volume_above_one_gb'


def test_legacy_unlimited_marker_remains_supported():
    result = eligible(page_text='ALDI TALK Unlimited')
    assert result['refill_eligible'] is True
    assert result['tariff_evidence'] == 'UNLIMITED'


def test_paid_offer_is_rejected():
    result = eligible(offer_text='1 GB Highspeed-Datenvolumen für 2,99 € nachbuchen')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'


def test_verified_tariff_without_local_zero_price_is_blocked():
    result = eligible(offer_text='1 GB Highspeed-Datenvolumen nachbuchen')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'


def test_multiple_candidate_controls_are_rejected():
    result = eligible(candidate_count=2)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'refill_control_ambiguous'
    assert result['refill_candidate_count'] == 2


def test_wrong_tariff_is_rejected():
    result = eligible(page_text='ALDI TALK Jahrespaket Datenvolumen')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'active_tariff_unverified'


def test_non_one_gb_offer_is_rejected():
    result = eligible(offer_text='2 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 €')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'not_exactly_one_gb'


def test_disabled_button_is_rejected():
    result = eligible(enabled=False)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'button_disabled'


def test_conflicting_terms_are_rejected_even_with_zero_price():
    result = eligible(offer_text='1 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 € monatlich')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'conflicting_terms'


def test_current_plain_tarif_s_m_l_is_not_verified_unlimited():
    for size in ('S', 'M', 'L'):
        result = eligible(page_text=f'ALDI TALK Tarif {size}',
                          active_tariff_text=f'Tarif {size}',
                          offer_text='1 GB Highspeed-Datenvolumen nachbuchen 0,00 €')
        assert result['refill_eligible'] is False
        assert result['refill_reason'] == 'not_unlimited_tariff'


def test_current_tarif_s_with_explicit_zero_is_not_unlimited():
    result = eligible(page_text='Übersicht Tarif S',
                      active_tariff_text='Tarif S',
                      offer_text='1 GB Highspeed-Datenvolumen kostenlos nachbuchen 0,00 €',
                      button_text='+1 GB')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'not_unlimited_tariff'


def test_current_tarif_s_without_local_price_is_blocked():
    result = eligible(page_text='Tarif S',
                      active_tariff_text='Tarif S',
                      offer_text='+1 GB Highspeed-Datenvolumen nachbuchen',
                      button_text='+1 GB')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'not_unlimited_tariff'


def test_tarif_s_paid_one_gb_offer_is_rejected():
    result = eligible(
        page_text='Tarif S',
        active_tariff_text='Tarif S',
        offer_text='1 GB Highspeed-Datenvolumen nachbuchen 0,99 €',
        button_text='+1 GB',
    )
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'not_unlimited_tariff'


def test_annual_tariff_and_generic_unlimited_hint_are_rejected():
    for tariff in ('Jahres-Paket XS', 'Jahrespaket S', 'Jahrestarif',
                   'Jahres Tarif', 'Basis-Tarif'):
        result = eligible(page_text=f'{tariff}\nALDI TALK Unlimited')
        assert result['refill_eligible'] is False


def test_unlimited_in_marketing_text_is_not_a_tariff_identity():
    result = eligible(page_text='Mit Unlimited kannst du kostenlos 1 GB nachbuchen')
    assert result['refill_eligible'] is False


def test_minutes_and_sms_unlimited_do_not_authorize_data_refill():
    result = eligible(page_text='Unbegrenzt Min.\nUnbegrenzt SMS')
    assert result['refill_eligible'] is False


def test_live_tariff_heading_overrides_generic_body_hint():
    result = eligible(page_text='ALDI TALK Unlimited',
                      active_tariff_text='Jahres-Paket S')
    assert result['refill_eligible'] is False


def test_missing_live_tariff_heading_fails_closed():
    result = eligible(page_text='ALDI TALK Unlimited', active_tariff_text='')
    assert result['refill_eligible'] is False


def test_explicit_unlimited_heading_with_verified_free_offer_is_eligible():
    result = eligible(page_text='Übersicht Guthaben Datenvolumen',
                      active_tariff_text='Tarif M Unlimited')
    assert result['refill_eligible'] is True


def test_multiple_unlimited_tariff_headings_are_ambiguous():
    result = eligible(active_tariff_text='Tarif S Unlimited\nTarif M Unlimited')
    assert result['refill_eligible'] is False


def test_refill_heading_alone_is_not_active_tariff_evidence():
    result = eligible(active_tariff_text="Unlimited GB nachbuchen")
    assert result["refill_eligible"] is False
    assert result["refill_reason"] == "active_tariff_unverified"


@pytest.mark.parametrize('offer', [
    '1 GB Datenvolumen nachbuchen 0,000 €',
    '1 GB Datenvolumen nachbuchen -0,00 €',
    '1 GB Datenvolumen nachbuchen −0,00 €',
    '1 GB Datenvolumen nachbuchen + 0,00 €',
    '1 GB Datenvolumen nachbuchen .0 €',
    '1 GB Datenvolumen nachbuchen 0,00, €',
    '1 GB Datenvolumen nachbuchen 0,00 € und 1,234 €',
    '1 GB Datenvolumen nachbuchen 0,00 € und 0,01 EUR',
])
def test_every_present_price_must_be_an_explicit_well_formed_zero(offer):
    result = eligible(offer_text=offer)
    assert not result['refill_eligible']
    assert result['refill_reason'] == 'price_unverified_or_paid'


def test_free_word_without_currency_is_not_price_evidence():
    result = eligible(offer_text='1 GB Datenvolumen kostenlos nachbuchen')
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'


@pytest.mark.parametrize('quantity', [
    '-1 GB', '−1 GB', '- 1 GB', '.1 GB', '1,000 GB',
    '1 GB und .2 GB', '1 GB und 1 MB', '1 GB und 1 KB', '1 GB und 1 GiB',
])
def test_all_data_units_must_prove_the_exact_one_gb_offer(quantity):
    result = eligible(offer_text=f'{quantity} Datenvolumen nachbuchen 0,00 €')
    assert not result['refill_eligible']
    assert result['refill_reason'] == 'not_exactly_one_gb'


@pytest.mark.parametrize(('quantity', 'price', 'allowed'), [
    ('1GB', '0€', False), ('+1 GB', '0,00 €', True),
    ('1.0 GB', '0EUR', False), ('1GB', '0,00 €', True),
])
def test_exact_zero_and_observed_plus_one_gb_control(quantity, price, allowed):
    assert eligible(offer_text=f'{quantity} Datenvolumen nachbuchen {price}')['refill_eligible'] is allowed


PHONE = '01500000000'


def account_driver(phone=PHONE, subscriptions=None):
    driver = Mock(current_url=PORTAL_URL)
    encoded = base64.b64encode(phone.encode()).decode()
    driver.get_cookies.return_value = [{
        'name': 'lgrs_id', 'value': encoded, 'domain': '.alditalk-kundenportal.de', 'path': '/',
    }]
    driver.execute_async_script.return_value = {
        'ok': True,
        'subscriptions': [{'contractId': 'private-test-contract'}] if subscriptions is None else subscriptions,
    }
    return driver


def test_account_guard_uses_bounded_read_only_same_session_request_and_private_signature():
    driver = account_driver()
    signature = verify_account_selenium(driver, '+49 150 0000000')
    assert len(signature) == 64
    assert PHONE not in signature and 'private-test-contract' not in signature
    driver.set_script_timeout.assert_called_once_with(10)
    script, url, deadline = driver.execute_async_script.call_args.args
    assert 'method: \'GET\'' in script
    assert "credentials: 'same-origin'" in script
    assert "redirect: 'error'" in script
    assert 'AbortController' in script
    assert url.endswith('?msisdn=' + PHONE)
    assert deadline == 8000


@pytest.mark.parametrize('url', [
    'https://example.invalid/account',
    'http://www.alditalk-kundenportal.de/portal/auth/uebersicht/',
    'https://www.alditalk-kundenportal.de:8443/portal/auth/uebersicht/',
    'https://private:secret@www.alditalk-kundenportal.de/portal/auth/uebersicht/',
])
def test_account_guard_rejects_untrusted_origins_before_any_protected_fetch(url):
    driver = account_driver()
    driver.current_url = url
    with pytest.raises(Exception):
        verify_account_selenium(driver, PHONE)
    driver.execute_async_script.assert_not_called()


def test_account_mismatch_never_requests_other_account_data():
    driver = account_driver('01500000001')
    with pytest.raises(RuntimeError, match='account_mismatch'):
        verify_account_selenium(driver, PHONE)
    driver.execute_async_script.assert_not_called()


@pytest.mark.parametrize('value', ['', 'not-base64', base64.b64encode(b'not-a-phone').decode()])
def test_malformed_selected_account_is_rejected(value):
    driver = account_driver()
    driver.get_cookies.return_value[0]['value'] = value
    with pytest.raises(RuntimeError, match='account_cookie_unverified'):
        verify_account_selenium(driver, PHONE)
    driver.execute_async_script.assert_not_called()


def test_conflicting_selected_account_cookies_are_rejected():
    driver = account_driver()
    other = dict(driver.get_cookies.return_value[0])
    other['value'] = base64.b64encode(b'01500000001').decode()
    driver.get_cookies.return_value.append(other)
    with pytest.raises(RuntimeError, match='account_cookie_unverified'):
        verify_account_selenium(driver, PHONE)
    driver.execute_async_script.assert_not_called()


@pytest.mark.parametrize('subscriptions', [[], [{}], ['opaque'], None])
def test_protected_json_requires_nonempty_subscription_objects(subscriptions):
    driver = account_driver()
    driver.execute_async_script.return_value['subscriptions'] = subscriptions
    with pytest.raises(RuntimeError, match='protected_account_response_unverified'):
        verify_account_selenium(driver, PHONE)


def test_account_changed_during_protected_fetch_cannot_verify():
    driver = account_driver()
    original = driver.get_cookies.return_value
    other = account_driver('01500000001').get_cookies.return_value
    driver.get_cookies.side_effect = [original, other]
    with pytest.raises(RuntimeError, match='account_mismatch'):
        verify_account_selenium(driver, PHONE)


def test_subscription_changes_alter_private_binding_but_order_does_not():
    driver = account_driver(subscriptions=[{'contractId': 'first'}, {'contractId': 'second'}])
    initial = verify_account_selenium(driver, PHONE)
    driver.execute_async_script.return_value['subscriptions'].reverse()
    assert verify_account_selenium(driver, PHONE) == initial
    driver.execute_async_script.return_value['subscriptions'][0]['contractId'] = 'changed'
    assert verify_account_selenium(driver, PHONE) != initial


def test_tariff_binding_distinguishes_unlimited_tariff_sizes(monkeypatch):
    import browser_dom
    import watcher
    driver = Mock(current_url=PORTAL_URL)
    heading = Mock()
    monkeypatch.setattr(watcher, 'aldi_session_visible', lambda _: True)
    monkeypatch.setattr(browser_dom, 'find_visible_elements', lambda *_: [heading])
    text = ['Tarif M Unlimited']
    monkeypatch.setattr(browser_dom, 'rendered_text', lambda *_: text[0])
    first = tariff_identity_selenium(driver)
    text[0] = 'Tarif L Unlimited'
    assert tariff_identity_selenium(driver) != first


@pytest.mark.parametrize('wallet', [
    'Guthaben 0,01 €', 'Kontostand: 0,00 EUR', 'Prepaid-Guthaben 14,95 €',
])
def test_standalone_wallet_balance_is_not_offer_price(wallet):
    result = eligible(offer_text=f'{wallet}\n1 GB Datenvolumen nachbuchen 0,00 €')
    assert result['refill_eligible'] is True
    assert result['free_evidence'] == 'explicit_free_offer'
    no_price = eligible(offer_text=f'{wallet}\n1 GB Datenvolumen nachbuchen')
    assert no_price['refill_eligible'] is False
    assert no_price['refill_reason'] == 'price_unverified_or_paid'


@pytest.mark.parametrize('offer', [
    '1 GB Datenvolumen nachbuchen; vom Guthaben 0,99 € abziehen 0,00 €',
    '1 GB Datenvolumen nachbuchen\nAbbuchung vom Guthaben 0,99 €',
    '1 GB Datenvolumen nachbuchen\nGuthaben 0,99 € wird abgezogen',
    'Guthaben 0,99 € 1 GB Datenvolumen nachbuchen 0,00 €',
    '0,01 € 1 GB Datenvolumen nachbuchen 0,00 €',
])
def test_wallet_deduction_or_mixed_wallet_price_remains_blocked(offer):
    result = eligible(offer_text=offer)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'


@pytest.mark.parametrize('offer', [
    '1 GB Datenvolumen nachbuchen 0,00 € Tarifwechsel',
    '1 GB Datenvolumen nachbuchen 0,00 € monatlich',
    '1 GB Datenvolumen nachbuchen 0,00 € abbuchen',
])
def test_tariff_or_charge_terms_block_zero_offer(offer):
    result = eligible(offer_text=offer)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'conflicting_terms'


@pytest.mark.parametrize('quantity', [None, True, -1, '1', 1.0])
def test_noncanonical_candidate_count_blocks_without_exception(quantity):
    assert eligible(candidate_count=quantity)['refill_eligible'] is False


@pytest.mark.parametrize('offer', [
    '1 GB Datenvolumen nachbuchen 0,00 € + 1,99 Euro',
    '1 GB Datenvolumen nachbuchen 0,00 € und 2 Euro',
    '1 GB Datenvolumen nachbuchen 0,00 Euro',
])
def test_spelled_euro_prices_are_not_overlooked(offer):
    result = eligible(offer_text=offer)
    assert result['refill_eligible'] is False
    assert result['refill_reason'] == 'price_unverified_or_paid'
