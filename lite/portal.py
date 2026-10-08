"""ALDI's regular browser flow. Protected selectors require observed account evidence.

No invented API, CAPTCHA solver, session dump or automatic click retry is used.
"""
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from browser_dom import find_visible_elements, rendered_text, element_label
from monitoring import require_origin
from watcher import build_driver, dismiss_cookie_banner, ALDI_LOGIN_URL, ALDI_LOGIN_HOSTS
from lite.models import Offer, Snapshot, Confirmation


class PortalError(RuntimeError):
    """Only a classified, nonpersonal error is exposed."""
    def __init__(self, code):
        self.error_class = code
        super().__init__(code)


def normalized_number(value):
    if not isinstance(value, str) or not re.fullmatch(r"[+\d\s()\-]+", value):
        return ''
    value = re.sub(r"\D", "", value or "")
    if value.startswith("0049"):
        value = value[2:]
    if value.startswith("0"):
        value = "49" + value[1:]
    return value


def exactly_one_gb(text):
    quantities = re.findall(r"(?<![\w.,+\-])([+\-]?[\d][\d.,]*)\s*GB\b", text, re.I)
    return (bool(quantities) and len(quantities) == len(re.findall(r'(?<![A-Za-z])GB\b', text, re.I))
            and all(re.fullmatch(r'1(?:[.,]0{1,2})?', q) for q in quantities))


def assess_offer(text, button_label, enabled):
    """One scoped offer, exactly 1 GB and an explicit zero-euro price."""
    prices = re.findall(r"(?<![\w.,+\-])([+\-]?[\d][\d.,]*)\s*(?:€|EUR\b)", text, re.I)
    if not exactly_one_gb(text):
        return None
    if (not prices or len(prices) != len(re.findall(r'€|(?<![A-Za-z])EUR\b', text, re.I))
            or any(not re.fullmatch(r'0(?:[.,]0{1,2})?', p) for p in prices)):
        return None
    if re.search(r"\b(?:kostenpflichtig|einmalig\s+\d|monatlich\s+\d)\b", text, re.I):
        return None
    if not enabled or not re.search(r"nachbuch|nachlad|refill", button_label, re.I):
        return None
    return Offer(data_mb=1000, price_cents=0, free_unlimited=True)


@dataclass(frozen=True)
class PortalConfig:
    account_selector: str = ""
    tariff_selector: str = ""
    offer_selector: str = ""
    button_selector: str = ""
    success_selector: str = ""
    pending_selector: str = ""
    pending_none_text: str = ""
    expected_tariff: str = ""

    @classmethod
    def from_env(cls):
        return cls(**{key: os.getenv("ALDI_" + key.upper(), "").strip()
                      for key in cls.__dataclass_fields__})

    def configured(self):
        return all(getattr(self, key) for key in self.__dataclass_fields__)


class AldiPortal:
    def __init__(self, config=None, driver_factory=build_driver, wait_seconds=30):
        self.config = config or PortalConfig.from_env()
        self.driver_factory = driver_factory
        self.wait_seconds = wait_seconds
        self.driver = None
        self.phase = 'not_started'
        self.username = ''.join(os.getenv('ALDI_USER', '').split())
        self.password = os.getenv('ALDI_PASS', '')

    def _origin(self, login=False):
        require_origin(self.driver, ALDI_LOGIN_URL,
                       login_hosts=ALDI_LOGIN_HOSTS if login else ())

    def _unique(self, selector, scope=None):
        values = find_visible_elements(self.driver, selector, scope)
        if len(values) != 1:
            raise PortalError('protected_element_unverified')
        return values[0]

    def _session(self):
        actual = urlsplit(self.driver.current_url)
        if (actual.scheme == 'https' and actual.hostname in ALDI_LOGIN_HOSTS
                and actual.path.startswith('/signin/XUI/')):
            return False
        self._origin()
        passwords = find_visible_elements(self.driver, "input[type='password']")
        logout = [e for e in find_visible_elements(self.driver, "a,button,[role='button']")
                  if element_label(self.driver, e).strip().casefold() in {'abmelden', 'logout'}]
        return not passwords and len(logout) == 1 and bool(self.driver.get_cookies())

    def login(self):
        if self.driver is not None:
            if self._session():
                return
            self.close()
        if not self.username or not self.password:
            raise PortalError('credentials_missing')
        self.phase = 'browser_start'
        self.driver = self.driver_factory()
        self.phase = 'login_page'
        self.driver.get(ALDI_LOGIN_URL)
        self._origin(login=True)
        dismiss_cookie_banner(self.driver)
        wait = WebDriverWait(self.driver, self.wait_seconds)
        def unique_enabled(selector):
            values = find_visible_elements(self.driver, selector)
            return values[0] if len(values) == 1 and values[0].is_enabled() else False
        try:
            self.phase = 'username_field'
            username = wait.until(lambda _: unique_enabled("input[autocomplete='username']"))
            self._origin(login=True)
            username.clear()
            username.send_keys(self.username)
            self.phase = 'password_field'
            password = wait.until(lambda _: unique_enabled("input[type='password']"))
            self._origin(login=True)
            password.clear()
            password.send_keys(self.password)
            self.phase = 'submit_control'
            def submit(_):
                buttons = [e for e in find_visible_elements(self.driver, "button,a,[role='button'],input[type='submit']")
                           if element_label(self.driver, e).strip().casefold() == 'anmelden'
                           and e.is_enabled() and e.get_attribute('aria-disabled') != 'true']
                return buttons[0] if len(buttons) == 1 else False
            button = wait.until(submit)
            self._origin(login=True)
            self.phase = 'login_submit'
            button.click()  # A login submission is never repeated on a timeout.
            self.phase = 'session_validation'
            wait.until(lambda _: self._session())
            self.phase = 'login_confirmed'
        except TimeoutException:
            challenges = find_visible_elements(self.driver, "iframe[src*='captcha'],iframe[src*='challenge'],.g-recaptcha,.h-captcha,input[autocomplete='one-time-code']")
            raise PortalError('user_action_required' if challenges else 'login_not_confirmed') from None

    def inspect(self):
        if not self.config.configured():
            raise PortalError('account_flow_unconfigured')
        self.login()
        if not self._session():
            raise PortalError('session_unverified')
        c = self.config
        account_text = rendered_text(self.driver, self._unique(c.account_selector))
        # Account selector must contain the exact current number alone, never a greeting.
        expected_number = normalized_number(self.username)
        account_ok = bool(expected_number) and normalized_number(account_text) == expected_number
        tariff_text = rendered_text(self.driver, self._unique(c.tariff_selector))
        tariff_ok = tariff_text.strip() == c.expected_tariff
        pending_text = rendered_text(self.driver, self._unique(c.pending_selector)).strip()
        # Unknown provider state counts as pending, never as proof of absence.
        pending = pending_text != c.pending_none_text
        offers = find_visible_elements(self.driver, c.offer_selector)
        offer = None
        if len(offers) == 1:
            button = self._unique(c.button_selector, offers[0])
            enabled = (button.is_enabled() and button.get_attribute('disabled') is None
                       and button.get_attribute('aria-disabled') != 'true')
            offer = assess_offer(rendered_text(self.driver, offers[0]),
                                 element_label(self.driver, button), enabled)
        elif len(offers) > 1:
            raise PortalError('ambiguous_refill_offer')
        return Snapshot(account_verified=account_ok, tariff_verified=tariff_ok,
                        offer=offer, pending_booking=pending)

    def book(self, recharge_id, offer):
        # Last inspection must still prove all facts immediately before clicking.
        current = self.inspect()
        if (not current.account_verified or not current.tariff_verified or current.pending_booking
                or current.offer != offer or offer is None):
            return Confirmation('FAILED', error_class='preclick_evidence_changed')
        if find_visible_elements(self.driver, self.config.success_selector):
            return Confirmation('FAILED', error_class='stale_success_notice')
        scoped_offer = self._unique(self.config.offer_selector)
        button = self._unique(self.config.button_selector, scoped_offer)
        self._origin()
        try:
            button.click()  # Exactly one attempt; no JS fallback, API fallback or retry.
            def confirmed(_):
                notices = find_visible_elements(self.driver, self.config.success_selector)
                if len(notices) != 1:
                    return False
                text = rendered_text(self.driver, notices[0])
                return (exactly_one_gb(text)
                        and re.search(r'\berfolgreich\b', text, re.I)
                        and re.search(r'\b(?:nachgebucht|gebucht|nachgeladen)\b', text, re.I)
                        and not re.search(r'\b(?:nicht|fehler|fehlgeschlagen)\b', text, re.I))
            WebDriverWait(self.driver, self.wait_seconds).until(confirmed)
            self._origin()
            return Confirmation('SUCCESS')
        except Exception:
            return Confirmation('UNKNOWN', error_class='provider_check_required')

    def reconcile(self, record):
        # A refreshed allowance or available button cannot identify a previous booking.
        # Until authenticated provider history/ID semantics are observed, never infer
        # FAILED or SUCCESS and never release a PENDING/UNKNOWN reservation.
        self.login()
        return Confirmation('UNKNOWN', error_class='provider_history_unverified')

    def close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            finally:
                self.driver = None
