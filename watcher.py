import os
import time
from urllib.parse import urlsplit
from core.credentials import get_credential
from browser_dom import find_visible_elements, element_label, rendered_text
from core.lidl_refill import inspect_selenium
from monitoring import run_cli, phase, session_visible, navigate, remaining_gb, require_origin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException,
    ElementClickInterceptedException, ElementNotInteractableException
)

# ===== KONFIGURATION =====
# Keep the SIM/account identifier separate from the portal login identifier.
# ALDI_LOGIN_USER may be an alternative A-... username. If it is absent, the
# existing ALDI_USER value remains the backwards-compatible login fallback.
ALDI_ACCOUNT_USER = ''.join(os.environ.get('ALDI_USER', '').split())
ALDI_USER = ''.join((os.environ.get('ALDI_LOGIN_USER') or os.environ.get('ALDI_USER', '')).split())
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


def configure_credentials(prefix):
    if prefix == 'ALDI':
        account_user = get_credential('ALDI_USER') or ''
        login_user = get_credential('ALDI_LOGIN_USER') or account_user
        password = get_credential('ALDI_PASS') or ''
        globals()['ALDI_ACCOUNT_USER'] = ''.join(account_user.split())
        globals()['ALDI_USER'] = ''.join(login_user.split())
        globals()['ALDI_PASS'] = password
        return bool(login_user and password)

    user = get_credential(prefix + '_USER') or ''
    password = get_credential(prefix + '_PASS') or ''
    globals()[prefix + '_USER'] = user
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


def aldi_session_visible(driver) -> bool:
    """Confirm a protected ALDI session without requiring a visible logout control."""
    try:
        require_origin(driver, ALDI_OVERVIEW_URL)
    except PermissionError:
        return False

    # Keep the existing strong signal when ALDI exposes an explicit logout control.
    if session_visible(driver):
        return True

    try:
        if not driver.get_cookies():
            return False
        if find_visible_elements(driver, "input[type='password']"):
            return False
        text = rendered_text(driver).casefold()
    except Exception:
        return False

    # These are protected customer-area concepts; require several to avoid
    # treating a generic public/error page as an authenticated overview.
    marker_groups = (
        ('guthaben',),
        ('datenvolumen', 'verbrauch', 'restvolumen', 'verbleibend', 'verfügbar'),
        ('inland', 'tarif', 'unlimited'),
    )
    matched_groups = sum(any(marker in text for marker in group) for group in marker_groups)
    return matched_groups >= 2


# ============================================================
# ALDI TALK
# ============================================================

def aldi_login(driver) -> bool:
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

    user_field = wait.until(
        lambda _: unique_enabled("input[autocomplete='username'],input[type='tel'],input[type='text']")
    )
    dismiss_cookie_banner(driver)
    require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
    # Component-backed inputs need keyboard edits and a blur/change event.
    user_field.send_keys(Keys.CONTROL, 'a')
    user_field.send_keys(Keys.BACKSPACE)
    user_field.send_keys(ALDI_USER)
    user_field.send_keys(Keys.TAB)
    phase('password_field')
    pass_field = wait.until(
        lambda _: unique_enabled("input[type='password']")
    )
    require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
    pass_field.send_keys(Keys.CONTROL, 'a')
    pass_field.send_keys(Keys.BACKSPACE)
    pass_field.send_keys(ALDI_PASS)
    pass_field.send_keys(Keys.TAB)

    def submit_control(_):
        require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
        buttons = [e for e in find_visible_elements(driver, "button,a,[role='button'],input[type='submit']")
                   if element_label(driver, e).strip().casefold() == 'anmelden'
                   and e.is_enabled() and e.get_attribute('aria-disabled') != 'true']
        return buttons[0] if len(buttons) == 1 else False

    button = wait.until(submit_control)
    phase('login_submit')
    require_origin(driver, ALDI_LOGIN_URL, login_hosts=ALDI_LOGIN_HOSTS)
    # Exactly one trusted DOM click. ALDI's component-backed login can re-render
    # during a native WebDriver click; invoking the element's click handler once
    # avoids that race while still exercising the real client-side auth flow.
    driver.execute_script("arguments[0].click();", button)

    def confirmed_portal_session(_):
        return aldi_session_visible(driver)

    phase('session_validation')
    try:
        # Give the normal SSO redirect a short chance to finish naturally.
        WebDriverWait(driver, min(WAIT_TIMEOUT, 8)).until(confirmed_portal_session)
        return True
    except TimeoutException:
        pass

    # A valid SSO session can exist even if the browser remains on the SSO host.
    # Probe the protected overview exactly once. Navigation is idempotent and does
    # not resubmit credentials or trigger any booking action.
    phase('protected_page_probe')
    navigate(driver, ALDI_OVERVIEW_URL, attempts=1)
    require_origin(driver, ALDI_OVERVIEW_URL, login_hosts=ALDI_LOGIN_HOSTS)
    wait.until(confirmed_portal_session)
    return True


def aldi_read_status(driver) -> dict:
    status = {'guthaben': '', 'inland_frei_gb': None}
    phase('protected_page')
    navigate(driver, ALDI_OVERVIEW_URL)
    require_origin(driver, ALDI_OVERVIEW_URL)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Guthaben')]")))
    time.sleep(2)
    if not aldi_session_visible(driver):
        raise PermissionError('session_invalid')
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
    # Rufnummer-Feld (aria-label="Mobilfunknummer" oder type=tel)
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
    # Login-Button
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
    # Sichtbare Session-Merkmale statt bereits passender Login-URL prüfen
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
    status.update(inspect_selenium(driver))
    return status


def main(argv=None):
    return run_cli(build_driver, {
        "aldi_talk": ("ALDI", aldi_login, aldi_read_status),
        "lidl_connect": ("LIDL", lidl_login, lidl_read_status),
    }, argv, credential_loader=configure_credentials)


if __name__ == '__main__':
    raise SystemExit(main())
