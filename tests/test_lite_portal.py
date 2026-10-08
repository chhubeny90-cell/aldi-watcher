"""Protected browser-flow checks with deterministic local fakes; no ALDI account."""

from dataclasses import dataclass, field

import pytest
from selenium.common.exceptions import TimeoutException

import lite.portal as portal_module
from lite.models import Offer
from lite.portal import AldiPortal, PortalConfig, PortalError, assess_offer


@dataclass
class Element:
    text: str = ''
    enabled: bool = True
    attrs: dict = field(default_factory=dict)
    clicks: int = 0
    value: str = ''
    on_click: object = None

    def is_enabled(self):
        return self.enabled

    def get_attribute(self, name):
        return self.attrs.get(name)

    def click(self):
        self.clicks += 1
        if self.on_click:
            self.on_click()

    def clear(self):
        self.value = ''

    def send_keys(self, value):
        self.value += value


class Driver:
    def __init__(self):
        self.current_url = portal_module.ALDI_LOGIN_URL
        self.elements = {}
        self.cookies = [{'name': 'synthetic-session', 'value': 'test-only'}]
        self.navigations = []
        self.quit_count = 0

    def get_cookies(self):
        return self.cookies

    def get(self, url):
        self.navigations.append(url)

    def quit(self):
        self.quit_count += 1


class ImmediateWait:
    """Poll only fake DOM state; timeouts never delay the test suite."""

    def __init__(self, driver, seconds):
        self.driver = driver

    def until(self, condition):
        for _ in range(3):
            value = condition(self.driver)
            if value:
                return value
        raise TimeoutException('private browser diagnostics must not be exposed')


@pytest.fixture
def browser(monkeypatch):
    driver = Driver()
    monkeypatch.setattr(portal_module, 'WebDriverWait', ImmediateWait)
    monkeypatch.setattr(portal_module, 'find_visible_elements',
                        lambda d, selector, scope=None: d.elements.get((selector, id(scope)), []))
    monkeypatch.setattr(portal_module, 'rendered_text', lambda d, e: e.text)
    monkeypatch.setattr(portal_module, 'element_label', lambda d, e: e.text)
    monkeypatch.setattr(portal_module, 'dismiss_cookie_banner', lambda d: None)
    return driver


@pytest.fixture
def protected_portal(browser, monkeypatch):
    monkeypatch.setenv('ALDI_USER', '+49 170 0000001')
    monkeypatch.setenv('ALDI_PASS', 'synthetic-password')
    config = PortalConfig(
        account_selector='#account', tariff_selector='#tariff',
        offer_selector='#offer', button_selector='button',
        success_selector='#success', pending_selector='#pending',
        pending_none_text='Keine Nachbuchung läuft', expected_tariff='Test Tarif')
    portal = AldiPortal(config, driver_factory=lambda: browser)
    portal.driver = browser
    account = Element('+49 170 0000001')
    tariff = Element('Test Tarif')
    offer = Element('1 GB nachbuchen für 0,00 €')
    pending = Element('Keine Nachbuchung läuft')
    button = Element('1 GB nachbuchen')
    for selector, element in (
        ('#account', account), ('#tariff', tariff), ('#offer', offer),
        ('#pending', pending), ("a,button,[role='button']", Element('Abmelden')),
    ):
        browser.elements[(selector, id(None))] = [element]
    browser.elements[('button', id(offer))] = [button]
    return portal, browser, account, tariff, offer, pending, button


@pytest.mark.parametrize('price', ['0 €', '0,00 €', '0.00 EUR'])
def test_exact_free_one_gb_offer_is_recognized(price):
    assert assess_offer(f'1 GB nachbuchen für {price}', 'Nachbuchen', True) == Offer(1000, 0, True)


def test_compact_one_gb_label_remains_a_valid_explicit_quantity():
    assert assess_offer('1GB nachbuchen für 0€', 'Nachbuchen', True) == Offer(1000, 0, True)


@pytest.mark.parametrize('text', [
    '1 GB für 0,01 €',
    '1 GB für 1,00 €',
    '1 GB für 0,00 €; danach 4,99 €',
    '1 GB und 2 GB für 0,00 €',
    '10 GB für 0,00 €',
    '0,1 GB für 0,00 €',
    '-1 GB für 0,00 €',
    '1 GB kostenlos',
    '1 GB für 0,000 €',
    '1 GB für -0,00 €',
    '1 GB für .0 €',
    '1 GB für 0,00, €',
    '1 GB für 0,00 €; zusätzliche Kosten 1,234 €',
    '1 GB für 0,00 €, kostenpflichtig',
])
def test_paid_ambiguous_or_malformed_offer_is_rejected(text):
    assert assess_offer(text, 'Nachbuchen', True) is None


@pytest.mark.parametrize(('label', 'enabled'), [('Details', True), ('Nachbuchen', False)])
def test_action_must_be_enabled_and_explicitly_a_refill(label, enabled):
    assert assess_offer('1 GB für 0,00 €', label, enabled) is None


def test_inspect_requires_exact_account_tariff_and_known_no_pending_state(protected_portal):
    portal, _, account, tariff, _, pending, _ = protected_portal
    snapshot = portal.inspect()
    assert snapshot.account_verified and snapshot.tariff_verified
    assert not snapshot.pending_booking
    assert snapshot.offer == Offer(1000, 0, True)
    account.text = '+49 170 0000002'
    tariff.text = 'Anderer Tarif'
    pending.text = 'Status unbekannt'
    snapshot = portal.inspect()
    assert not snapshot.account_verified and not snapshot.tariff_verified
    assert snapshot.pending_booking


def test_account_selector_must_not_normalize_arbitrary_text_into_identity(protected_portal):
    portal, _, account, _, _, _, _ = protected_portal
    account.text = 'Kundennummer: +49 170 0000001'
    assert not portal.inspect().account_verified


def test_empty_number_cannot_verify_an_invalid_account_identifier(protected_portal):
    portal, _, account, _, _, _, _ = protected_portal
    portal.username = 'synthetic@example.invalid'
    account.text = ''
    assert not portal.inspect().account_verified


def test_multiple_offers_are_ambiguous(protected_portal):
    portal, driver, _, _, offer, _, _ = protected_portal
    driver.elements[('#offer', id(None))] = [offer, Element('1 GB 0,00 €')]
    with pytest.raises(PortalError, match='ambiguous_refill_offer'):
        portal.inspect()


@pytest.mark.parametrize('change', ['account', 'tariff', 'price', 'pending', 'disabled'])
def test_book_revalidates_provider_before_click(protected_portal, change):
    portal, _, account, tariff, offer, pending, button = protected_portal
    observed = portal.inspect().offer
    if change == 'account':
        account.text = '+49 170 0000002'
    elif change == 'tariff':
        tariff.text = 'Anderer Tarif'
    elif change == 'price':
        offer.text = '1 GB für 4,99 €'
    elif change == 'pending':
        pending.text = 'Nachbuchung läuft'
    else:
        button.enabled = False
    result = portal.book('synthetic-recharge', observed)
    assert result.status == 'FAILED'
    assert result.error_class == 'preclick_evidence_changed'
    assert button.clicks == 0


def test_stale_success_notice_never_confirms_a_new_booking(protected_portal):
    portal, driver, _, _, _, _, button = protected_portal
    driver.elements[('#success', id(None))] = [Element('1 GB erfolgreich nachgebucht')]
    result = portal.book('synthetic-recharge', portal.inspect().offer)
    assert result.status == 'FAILED'
    assert result.error_class == 'stale_success_notice'
    assert button.clicks == 0


def test_new_specific_provider_confirmation_marks_success(protected_portal):
    portal, driver, _, _, _, _, button = protected_portal
    button.on_click = lambda: driver.elements.update({
        ('#success', id(None)): [Element('1 GB erfolgreich nachgebucht')]})
    assert portal.book('synthetic-recharge', portal.inspect().offer).status == 'SUCCESS'
    assert button.clicks == 1


@pytest.mark.parametrize('notice', [
    None, 'Erfolgreich', '2 GB erfolgreich nachgebucht',
    '1 GB nicht erfolgreich nachgebucht', '1 GB nachgebucht, Fehler',
    '-1 GB erfolgreich nachgebucht',
    '1 GB und .2 GB erfolgreich nachgebucht',
])
def test_timeout_or_incomplete_confirmation_is_unknown_without_click_retry(protected_portal, notice):
    portal, driver, _, _, _, _, button = protected_portal
    if notice:
        button.on_click = lambda: driver.elements.update({
            ('#success', id(None)): [Element(notice)]})
    result = portal.book('synthetic-recharge', portal.inspect().offer)
    assert result.status == 'UNKNOWN'
    assert result.error_class == 'provider_check_required'
    assert button.clicks == 1


def test_click_timeout_is_unknown_and_is_never_retried(protected_portal):
    portal, _, _, _, _, _, button = protected_portal
    def timeout():
        raise TimeoutException('possibly already booked; private driver text')
    button.on_click = timeout
    result = portal.book('synthetic-recharge', portal.inspect().offer)
    assert result.status == 'UNKNOWN'
    assert result.error_class == 'provider_check_required'
    assert button.clicks == 1


def test_sso_transition_is_not_treated_as_an_authenticated_portal(browser):
    portal = AldiPortal(driver_factory=lambda: browser)
    portal.driver = browser
    browser.current_url = 'https://login.alditalk-kundenbetreuung.de/signin/XUI/'
    assert portal._session() is False


def test_untrusted_origin_is_rejected_before_protected_dom_reads(browser):
    portal = AldiPortal(driver_factory=lambda: browser)
    portal.driver = browser
    browser.current_url = 'https://example.invalid/phishing'
    with pytest.raises(PermissionError, match='unexpected_origin'):
        portal._session()


def login_controls(driver):
    username = Element()
    password = Element()
    submit = Element('Anmelden')
    driver.current_url = 'https://login.alditalk-kundenbetreuung.de/signin/XUI/'
    for selector, element in (
        ("input[autocomplete='username']", username),
        ("input[type='password']", password),
        ("button,a,[role='button'],input[type='submit']", submit),
    ):
        driver.elements[(selector, id(None))] = [element]
    return username, password, submit


def test_login_waits_for_regular_sso_redirect_without_resubmitting(browser, monkeypatch):
    monkeypatch.setenv('ALDI_USER', '+49 170 0000001')
    monkeypatch.setenv('ALDI_PASS', 'synthetic-password')
    username, password, submit = login_controls(browser)

    class RedirectWait(ImmediateWait):
        def until(self, condition):
            for _ in range(3):
                value = condition(self.driver)
                if value:
                    return value
                if submit.clicks:
                    browser.current_url = portal_module.ALDI_LOGIN_URL
                    browser.elements[("input[type='password']", id(None))] = []
                    browser.elements[("a,button,[role='button']", id(None))] = [Element('Abmelden')]
            raise TimeoutException()

    monkeypatch.setattr(portal_module, 'WebDriverWait', RedirectWait)
    portal = AldiPortal(driver_factory=lambda: browser)
    portal.login()
    assert username.value == '+491700000001'
    assert password.value == 'synthetic-password'
    assert submit.clicks == 1
    assert browser.navigations == [portal_module.ALDI_LOGIN_URL]
    assert portal._session()


@pytest.mark.parametrize('captcha', [False, True])
def test_login_timeout_never_retries_or_bypasses_a_challenge(browser, monkeypatch, captcha):
    monkeypatch.setenv('ALDI_USER', '+49 170 0000001')
    monkeypatch.setenv('ALDI_PASS', 'synthetic-password')
    _, _, submit = login_controls(browser)
    if captcha:
        selector = "iframe[src*='captcha'],iframe[src*='challenge'],.g-recaptcha,.h-captcha,input[autocomplete='one-time-code']"
        browser.elements[(selector, id(None))] = [Element('synthetic challenge')]
    portal = AldiPortal(driver_factory=lambda: browser)
    expected = 'user_action_required' if captcha else 'login_not_confirmed'
    with pytest.raises(PortalError, match=expected):
        portal.login()
    assert submit.clicks == 1
    assert browser.navigations == [portal_module.ALDI_LOGIN_URL]


def test_otp_requires_user_action_without_filling_or_resubmitting(browser, monkeypatch):
    monkeypatch.setenv('ALDI_USER', '+49 170 0000001')
    monkeypatch.setenv('ALDI_PASS', 'synthetic-password')
    _, _, submit = login_controls(browser)
    otp = Element(attrs={'autocomplete': 'one-time-code'})
    selector = "iframe[src*='captcha'],iframe[src*='challenge'],.g-recaptcha,.h-captcha,input[autocomplete='one-time-code']"
    browser.elements[(selector, id(None))] = [otp]
    portal = AldiPortal(driver_factory=lambda: browser)
    with pytest.raises(PortalError, match='user_action_required'):
        portal.login()
    assert otp.value == ''
    assert otp.clicks == 0
    assert submit.clicks == 1


def test_unconfigured_account_flow_does_not_start_browser(browser):
    portal = AldiPortal(PortalConfig(), driver_factory=lambda: pytest.fail('no browser before evidence config'))
    with pytest.raises(PortalError, match='account_flow_unconfigured'):
        portal.inspect()
    assert browser.navigations == []


def test_reconcile_never_infers_failure_or_success_from_available_button(protected_portal):
    portal, _, _, _, _, _, button = protected_portal
    result = portal.reconcile(object())
    assert result.status == 'UNKNOWN'
    assert result.error_class == 'provider_history_unverified'
    assert button.clicks == 0
