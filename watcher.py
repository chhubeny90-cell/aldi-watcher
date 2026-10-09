import os
import time
from urllib.parse import urlsplit
from core.credentials import get_credential
from browser_dom import find_visible_elements, element_label
from core.aldi_refill import (
    inspect_selenium as inspect_aldi_refill,
    inspect_reconciliation_selenium as inspect_aldi_reconciliation,
)
from core.lidl_refill import inspect_selenium as inspect_lidl_refill
from monitoring import run_cli, phase, session_visible, navigate, remaining_gb, require_origin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, WebDriverException,
    ElementClickInterceptedException, ElementNotInteractableException
)

# ===== KONFIGURATION =====
ALDI_USER = ''.join(os.environ.get('ALDI_USER', '').split())
ALDI_PASS = os.environ.get('ALDI_PASS', '')
LIDL_USER = os.environ.get('LIDL_USER', '')
LIDL_PASS = os.environ.get('LIDL_PASS', '')

# Current customer-area link published on https://www.alditalk.de/.
ALDI_LOGIN_URL = 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'
ALDI_OVERVIEW_URL = ALDI_LOGIN_URL
# Observed redirect from the configured ALDI portal; official ALDI login host.
ALDI_LOGIN_HOSTS = ('login.alditalk-kundenbetreuung.de',)
# Official www.lidl-connect.de customer-account link redirects to this page.
LIDL_LOGIN_URL = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect.html'
LIDL_OVERVIEW_URL = LIDL_LOGIN_URL

WAIT_TIMEOUT = 30
ALDI_AUTH_DIAGNOSTIC_STATE = {}


def configure_credentials(prefix):
    user = get_credential(prefix + '_USER') or ''
    password = get_credential(prefix + '_PASS') or ''
    globals()[prefix + '_USER'] = ''.join(user.split()) if prefix == 'ALDI' else user
    globals()[prefix + '_PASS'] = password
    return bool(user and password)


def build_driver():
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1400,1000')
    options.add_argument('--lang=de-DE')
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL', 'browser': 'ALL'})
    chrome_binary = os.environ.get('CHROME_BINARY')
    if chrome_binary:
        options.binary_location = chrome_binary
    driver_path = os.environ.get('CHROMEDRIVER_PATH')
    service = Service(executable_path=driver_path) if driver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(20)
    return driver


def dismiss_cookie_banner(driver):
    selectors = [
        "//button[contains(., 'Alle akzeptieren')]",
        "//button[contains(., 'Akzeptieren')]",
        "//button[contains(., 'Zustimmen')]",
        "//button[@id='onetrust-accept-btn-handler']",
        "//button[contains(@class, 'accept')]",
        "//button[contains(@class, 'cookie')]",
    ]
    for sel in selectors:
        try:
            elems = driver.find_elements(By.XPATH, sel)
            for e in elems:
                if e.is_displayed() and e.is_enabled():
                    driver.execute_script("arguments[0].click();", e)
                    time.sleep(1)
                    return
        except Exception:
            continue


def safe_click(driver, element):
    try:
        element.click()
    except (ElementClickInterceptedException, ElementNotInteractableException):
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", element)


def _aldi_diagnostic_field_state(driver, element, prefix):
    """Record booleans only; never record a login field value or message."""
    result = {
        f'pre_submit_{prefix}_has_value': None,
        f'pre_submit_{prefix}_aria_invalid': None,
        f'pre_submit_{prefix}_native_valid': None,
        f'pre_submit_{prefix}_value_missing': None,
        f'pre_submit_{prefix}_pattern_mismatch': None,
        f'pre_submit_{prefix}_type_mismatch': None,
        f'pre_submit_{prefix}_too_short': None,
        f'pre_submit_{prefix}_too_long': None,
        f'pre_submit_{prefix}_custom_error': None,
    }
    try:
        result[f'pre_submit_{prefix}_has_value'] = bool(
            driver.execute_script('return Boolean(arguments[0].value);', element)
        )
    except Exception:
        pass
    try:
        result[f'pre_submit_{prefix}_aria_invalid'] = (
            (element.get_attribute('aria-invalid') or '').lower() == 'true'
        )
    except Exception:
        pass
    try:
        validity = driver.execute_script(
            """
            const v = arguments[0].validity;
            if (!v) return null;
            return {
              valid: Boolean(v.valid),
              valueMissing: Boolean(v.valueMissing),
              patternMismatch: Boolean(v.patternMismatch),
              typeMismatch: Boolean(v.typeMismatch),
              tooShort: Boolean(v.tooShort),
              tooLong: Boolean(v.tooLong),
              customError: Boolean(v.customError)
            };
            """,
            element,
        )
        if isinstance(validity, dict):
            result[f'pre_submit_{prefix}_native_valid'] = bool(validity.get('valid'))
            result[f'pre_submit_{prefix}_value_missing'] = bool(validity.get('valueMissing'))
            result[f'pre_submit_{prefix}_pattern_mismatch'] = bool(validity.get('patternMismatch'))
            result[f'pre_submit_{prefix}_type_mismatch'] = bool(validity.get('typeMismatch'))
            result[f'pre_submit_{prefix}_too_short'] = bool(validity.get('tooShort'))
            result[f'pre_submit_{prefix}_too_long'] = bool(validity.get('tooLong'))
            result[f'pre_submit_{prefix}_custom_error'] = bool(validity.get('customError'))
    except Exception:
        pass
    return result


def aldi_protected_session_visible(driver):
    """Confirm an ALDI session only on the protected customer portal.

    This deliberately does not treat disappearance of the login form as success.
    The browser must be on the official customer portal, have cookies, expose a
    protected account marker, and have no visible password field (including open
    shadow roots).
    """
    try:
        require_origin(driver, ALDI_OVERVIEW_URL)
        if not driver.get_cookies():
            return False
        if find_visible_elements(driver, "input[type='password']"):
            return False
        markers = driver.find_elements(
            By.XPATH,
            "//*[contains(normalize-space(.), 'Guthaben') or "
            "contains(normalize-space(.), 'Datenvolumen') or "
            "contains(normalize-space(.), 'Verbrauch')]"
        )
        return any(element.is_displayed() for element in markers)
    except Exception:
        return False


# ============================================================
# ALDI TALK
# ============================================================

def aldi_login(driver) -> bool:
    global ALDI_AUTH_DIAGNOSTIC_STATE
    ALDI_AUTH_DIAGNOSTIC_STATE = {}
    if not ALDI_USER or not ALDI_PASS:
        return False
    phase('login_page')
    navigate(driver, ALDI_LOGIN_URL)
    require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    dismiss_cookie_banner(driver)
    phase('username_field')

    def unique_enabled(selector):
        require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
        elements = find_visible_elements(driver, selector)
        return elements[0] if len(elements) == 1 and elements[0].is_enabled() else False

    user_selector = "input[autocomplete='username'],input[type='tel'],input[type='text']"
    password_selector = "input[type='password']"
    user_field = wait.until(lambda _: unique_enabled(user_selector))
    dismiss_cookie_banner(driver)
    require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
    # Use keyboard input and a real blur event rather than WebElement.clear().
    # The authenticated probe showed that ALDI's component can keep its internal
    # model empty even while the native input value looks valid. TAB gives the
    # component the same change/blur transition as an interactive login.
    user_field.send_keys(Keys.CONTROL, 'a')
    user_field.send_keys(Keys.BACKSPACE)
    user_field.send_keys(ALDI_USER)
    user_field.send_keys(Keys.TAB)

    phase('password_field')
    pass_field = wait.until(lambda _: unique_enabled(password_selector))
    require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
    pass_field.send_keys(Keys.CONTROL, 'a')
    pass_field.send_keys(Keys.BACKSPACE)
    pass_field.send_keys(ALDI_PASS)
    pass_field.send_keys(Keys.TAB)

    # Re-resolve controls after blur in case the component re-rendered them.
    user_field = wait.until(lambda _: unique_enabled(user_selector))
    pass_field = wait.until(lambda _: unique_enabled(password_selector))

    def submit_control(_):
        require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
        buttons = [e for e in find_visible_elements(driver, "button,a,[role='button'],input[type='submit']")
                   if element_label(driver, e).strip().casefold() == 'anmelden'
                   and e.is_enabled() and e.get_attribute('aria-disabled') != 'true']
        return buttons[0] if len(buttons) == 1 else False

    button = wait.until(submit_control)
    phase('login_submit')
    require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)

    diagnostic_mode = os.getenv('ALDI_AUTH_DIAGNOSTIC', 'false').strip().lower() == 'true'
    if diagnostic_mode:
        ALDI_AUTH_DIAGNOSTIC_STATE.update(
            _aldi_diagnostic_field_state(driver, user_field, 'username')
        )
        ALDI_AUTH_DIAGNOSTIC_STATE.update(
            _aldi_diagnostic_field_state(driver, pass_field, 'password')
        )
        try:
            driver.get_log('performance')
        except Exception:
            pass

    # Submit exactly once with a WebDriver keyboard event on the validated button.
    # This avoids an untrusted JavaScript click while keeping retries/fallbacks forbidden.
    button.send_keys(Keys.ENTER)
    if diagnostic_mode:
        ALDI_AUTH_DIAGNOSTIC_STATE['submit_attempted_once'] = True

    # Do not interrupt the provider's SSO callback chain with our own navigation.
    phase('sso_redirect')
    portal_host = urlsplit(ALDI_OVERVIEW_URL).hostname
    wait.until(lambda _: urlsplit(driver.current_url).hostname == portal_host)
    phase('protected_session_probe')
    require_origin(driver, ALDI_OVERVIEW_URL)
    wait.until(aldi_protected_session_visible)
    return True


def aldi_read_status(driver) -> dict:
    status = {'guthaben': '', 'inland_frei_gb': None}
    phase('protected_page')
    navigate(driver, ALDI_OVERVIEW_URL)
    require_origin(driver, ALDI_OVERVIEW_URL)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    wait.until(aldi_protected_session_visible)
    phase('usage_parse')
    body_text = driver.find_element(By.TAG_NAME, 'body').text
    for line in body_text.splitlines():
        if 'Guthaben' in line and status['guthaben'] == '':
            status['guthaben'] = line.strip()
    try:
        inland_label = driver.find_element(By.XPATH, "//*[text()='Inland']")
        container = inland_label.find_element(By.XPATH, "./ancestor::*[self::div or self::li][1]/..")
        text = container.text
        status['inland_frei_gb'] = remaining_gb(text)
    except NoSuchElementException:
        pass
    phase('refill_availability')
    status.update(inspect_aldi_refill(driver, ALDI_USER))
    phase('reconciliation_probe')
    status['reconciliation_status'] = inspect_aldi_reconciliation(driver, ALDI_USER)
    return status


# ============================================================
# LIDL CONNECT
# ============================================================

def lidl_login(driver) -> bool:
    if not LIDL_USER or not LIDL_PASS:
        return False
    phase('login_page')
    navigate(driver, LIDL_LOGIN_URL)
    require_origin(driver, LIDL_LOGIN_URL)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    dismiss_cookie_banner(driver)
    time.sleep(2)
    phase('username_field')
    user_field = wait.until(
        EC.visibility_of_element_located((
            By.XPATH,
            "//input[@aria-label='Mobilfunknummer' or @type='tel' or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'nummer')]"
        ))
    )
    user_field.clear()
    user_field.send_keys(LIDL_USER)
    phase('password_field')
    pass_field = wait.until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
    )
    pass_field.clear()
    pass_field.send_keys(LIDL_PASS)
    submit_candidates = driver.find_elements(
        By.XPATH,
        "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'einloggen') or "
        "contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'anmelden') or "
        "contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'login')] | "
        "//button[@type='submit']"
    )
    phase('login_submit')
    clicked = False
    for btn in submit_candidates:
        if btn.is_displayed() and btn.is_enabled():
            safe_click(driver, btn)
            clicked = True
            break
    if not clicked:
        pass_field.send_keys(Keys.ENTER)
    phase('session_validation')
    wait.until(session_visible)
    return True


def lidl_read_status(driver) -> dict:
    status = {'guthaben': '', 'inland_frei_gb': None}
    phase('protected_page')
    navigate(driver, LIDL_OVERVIEW_URL)
    require_origin(driver, LIDL_OVERVIEW_URL)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    wait.until(EC.presence_of_element_located((
        By.XPATH, "//*[contains(text(),'Guthaben') or contains(text(),'Datenvolumen') or contains(text(),'Verbrauch')]"
    )))
    time.sleep(3)
    if not session_visible(driver):
        raise PermissionError('session_invalid')
    phase('usage_parse')
    body_text = driver.find_element(By.TAG_NAME, 'body').text
    for line in body_text.splitlines():
        ll = line.lower()
        if ('guthaben' in ll or 'balance' in ll) and status['guthaben'] == '':
            status['guthaben'] = line.strip()
    status['inland_frei_gb'] = remaining_gb(body_text)
    phase('refill_availability')
    status.update(inspect_lidl_refill(driver))
    return status


def main(argv=None):
    return run_cli(build_driver, {
        "aldi_talk": ("ALDI", aldi_login, aldi_read_status),
        "lidl_connect": ("LIDL", lidl_login, lidl_read_status),
    }, argv, credential_loader=configure_credentials)


if __name__ == '__main__':
    raise SystemExit(main())
