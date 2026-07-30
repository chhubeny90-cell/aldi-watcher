import os
import sys
import time
import datetime
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException,
    ElementClickInterceptedException, ElementNotInteractableException
)

# ===== KONFIGURATION =====
ALDI_USER = os.environ.get('ALDI_USER', '')
ALDI_PASS = os.environ.get('ALDI_PASS', '')
LIDL_USER = os.environ.get('LIDL_USER', '')
LIDL_PASS = os.environ.get('LIDL_PASS', '')
AUTO_BOOK_ENABLED = os.environ.get('AUTO_BOOK_ENABLED', 'true').lower() == 'true'

ALDI_LOGIN_URL = 'https://www.alditalk-kundenportal.de/portal/noauth/login'
ALDI_OVERVIEW_URL = 'https://www.alditalk-kundenportal.de/user/auth/account-overview/'
LIDL_LOGIN_URL = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/uebersicht.html'
LIDL_OVERVIEW_URL = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/uebersicht.html'

WAIT_TIMEOUT = 30


def log(msg: str):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


def build_driver():
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1400,1000')
    options.add_argument('--lang=de-DE')
    options.add_argument(
        'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
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
                    log('Cookie-Banner weggeklickt.')
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


# ============================================================
# ALDI TALK
# ============================================================

def aldi_login(driver) -> bool:
    if not ALDI_USER or not ALDI_PASS:
        log('ALDI: ALDI_USER oder ALDI_PASS nicht gesetzt (Secrets fehlen).')
        return False
    try:
        driver.get(ALDI_LOGIN_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        dismiss_cookie_banner(driver)

        user_field = wait.until(
            EC.visibility_of_element_located((
                By.XPATH,
                "//input[@type='text' or @type='tel' or contains(translate(@aria-label,'RUFNUMER','rufnumer'),'rufnummer') or contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'user')]"
            ))
        )
        dismiss_cookie_banner(driver)
        user_field.clear()
        user_field.send_keys(ALDI_USER)

        pass_field = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
        )
        pass_field.clear()
        pass_field.send_keys(ALDI_PASS)

        submit_candidates = driver.find_elements(
            By.XPATH,
            "//button[contains(., 'Anmelden') and not(contains(., 'ohne Passwort'))] | "
            "//a[contains(., 'Anmelden') and not(contains(., 'ohne Passwort'))] | "
            "//button[@type='submit']"
        )
        clicked = False
        for btn in submit_candidates:
            if btn.is_displayed() and btn.is_enabled():
                safe_click(driver, btn)
                clicked = True
                break
        if not clicked:
            pass_field.send_keys(Keys.ENTER)

        wait.until(EC.any_of(
            EC.url_contains('uebersicht'),
            EC.url_contains('account-overview'),
            EC.url_contains('logged-in-home-page'),
        ))
        log('ALDI TALK: Login erfolgreich.')
        return True
    except TimeoutException:
        log('ALDI TALK: Login-Timeout.')
        try:
            driver.save_screenshot('aldi_login_timeout.png')
        except Exception:
            pass
        return False
    except Exception as e:
        log(f'ALDI TALK: Login-Fehler: {e}')
        return False


def aldi_read_status(driver) -> dict:
    status = {'guthaben': '', 'inland_frei_gb': None}
    try:
        driver.get(ALDI_OVERVIEW_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Guthaben')]")))
        time.sleep(2)
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        for line in body_text.splitlines():
            if 'Guthaben' in line and status['guthaben'] == '':
                status['guthaben'] = line.strip()
        try:
            inland_label = driver.find_element(By.XPATH, "//*[text()='Inland']")
            container = inland_label.find_element(By.XPATH, "./ancestor::*[self::div or self::li][1]/..")
            text = container.text
            m = re.search(r'(\d+[\.,]?\d*)\s*GB', text)
            if m:
                status['inland_frei_gb'] = float(m.group(1).replace(',', '.'))
        except NoSuchElementException:
            pass
        log(f'ALDI TALK Status: {status}')
        return status
    except Exception as e:
        log(f'ALDI TALK: Fehler beim Statusabruf: {e}')
        return status


def aldi_book_free_gb(driver) -> bool:
    if not AUTO_BOOK_ENABLED:
        log('Auto-Buchung deaktiviert - keine Aktion.')
        return False
    try:
        candidates = driver.find_elements(
            By.XPATH,
            "//*[contains(text(), '+1 GB') or contains(@aria-label, 'nachbuchen') or contains(text(), 'nachbuchen') or contains(text(), 'Highspeed')]"
        )
        clickable = [c for c in candidates if c.is_displayed() and c.is_enabled()]
        if not clickable:
            log('ALDI TALK: Keine aktive kostenlose Nachbuchoption gefunden.')
            return False
        safe_click(driver, clickable[0])
        time.sleep(1)
        confirm_buttons = driver.find_elements(
            By.XPATH,
            "//button[contains(text(), 'Bestätig') or contains(text(), 'Jetzt buchen') or contains(text(), 'Kostenlos')]"
        )
        for btn in confirm_buttons:
            if btn.is_displayed() and btn.is_enabled():
                safe_click(driver, btn)
                break
        log('ALDI TALK: Kostenlose 1 GB Inland-Nachbuchung ausgeloest.')
        return True
    except Exception as e:
        log(f'ALDI TALK: Fehler beim Ausloesen der Nachbuchung: {e}')
        return False


# ============================================================
# LIDL CONNECT
# ============================================================

def lidl_login(driver) -> bool:
    if not LIDL_USER or not LIDL_PASS:
        log('LIDL CONNECT: LIDL_USER oder LIDL_PASS nicht gesetzt (Secrets fehlen).')
        return False
    try:
        driver.get(LIDL_LOGIN_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        dismiss_cookie_banner(driver)
        time.sleep(2)

        # Rufnummer-Feld (aria-label="Mobilfunknummer" oder type=tel)
        user_field = wait.until(
            EC.visibility_of_element_located((
                By.XPATH,
                "//input[@aria-label='Mobilfunknummer' or @type='tel' or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'nummer')]"
            ))
        )
        user_field.clear()
        user_field.send_keys(LIDL_USER)

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
        clicked = False
        for btn in submit_candidates:
            if btn.is_displayed() and btn.is_enabled():
                safe_click(driver, btn)
                clicked = True
                break
        if not clicked:
            pass_field.send_keys(Keys.ENTER)

        # Nach Login: URL oder Seiteninhalt prüfen
        wait.until(EC.any_of(
            EC.url_contains('uebersicht'),
            EC.url_contains('dashboard'),
            EC.url_contains('mein-lidl'),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Guthaben') or contains(text(),'Datenvolumen') or contains(text(),'Verbrauch')]"))
        ))
        log('LIDL CONNECT: Login erfolgreich.')
        return True
    except TimeoutException:
        log('LIDL CONNECT: Login-Timeout.')
        try:
            driver.save_screenshot('lidl_login_timeout.png')
        except Exception:
            pass
        return False
    except Exception as e:
        log(f'LIDL CONNECT: Login-Fehler: {e}')
        return False


def lidl_read_status(driver) -> dict:
    status = {'guthaben': '', 'inland_frei_gb': None, 'raw': ''}
    try:
        driver.get(LIDL_OVERVIEW_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        wait.until(EC.presence_of_element_located((
            By.XPATH, "//*[contains(text(),'Guthaben') or contains(text(),'Datenvolumen') or contains(text(),'Verbrauch')]"
        )))
        time.sleep(3)
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        status['raw'] = body_text[:500]

        for line in body_text.splitlines():
            ll = line.lower()
            if ('guthaben' in ll or 'balance' in ll) and status['guthaben'] == '':
                status['guthaben'] = line.strip()

        # GB-Restvolumen suchen
        m = re.search(r'(\d+[\.,]?\d*)\s*GB\s*(verbleibend|frei|übrig|left|rest)?', body_text, re.IGNORECASE)
        if m:
            status['inland_frei_gb'] = float(m.group(1).replace(',', '.'))

        # Alternativ MB
        if status['inland_frei_gb'] is None:
            m_mb = re.search(r'(\d+[\.,]?\d*)\s*MB\s*(verbleibend|frei|übrig|left|rest)?', body_text, re.IGNORECASE)
            if m_mb:
                status['inland_frei_gb'] = round(float(m_mb.group(1).replace(',', '.')) / 1024, 3)

        log(f'LIDL CONNECT Status: Guthaben="{status["guthaben"]}", Daten={status["inland_frei_gb"]} GB')
        return status
    except Exception as e:
        log(f'LIDL CONNECT: Fehler beim Statusabruf: {e}')
        return status


def lidl_book_free_option(driver) -> bool:
    if not AUTO_BOOK_ENABLED:
        log('LIDL CONNECT: Auto-Buchung deaktiviert.')
        return False
    try:
        candidates = driver.find_elements(
            By.XPATH,
            "//*[contains(text(), '+1 GB') or contains(text(), 'Daten nachbuchen') or "
            "contains(text(), 'Kostenlos') or contains(@aria-label, 'nachbuchen') or "
            "contains(text(), 'Highspeed') or contains(text(), 'Gratis')]"
        )
        clickable = [c for c in candidates if c.is_displayed() and c.is_enabled()]
        if not clickable:
            log('LIDL CONNECT: Keine aktive kostenlose Nachbuchoption gefunden.')
            return False
        safe_click(driver, clickable[0])
        time.sleep(1.5)
        confirm_buttons = driver.find_elements(
            By.XPATH,
            "//button[contains(text(), 'Bestätig') or contains(text(), 'Jetzt buchen') or "
            "contains(text(), 'Kostenlos') or contains(text(), 'Buchen')]"
        )
        for btn in confirm_buttons:
            if btn.is_displayed() and btn.is_enabled():
                safe_click(driver, btn)
                log('LIDL CONNECT: Nachbuchung bestätigt.')
                break
        log('LIDL CONNECT: Buchungsversuch abgeschlossen.')
        return True
    except Exception as e:
        log(f'LIDL CONNECT: Fehler beim Buchen: {e}')
        return False


# ============================================================
# MAIN
# ============================================================

def run_aldi(driver):
    log('--- ALDI TALK ---')
    if not ALDI_USER or not ALDI_PASS:
        log('ALDI TALK: Secrets nicht gesetzt, überspringe.')
        return
    if not aldi_login(driver):
        return
    status = aldi_read_status(driver)
    if status['inland_frei_gb'] is not None and status['inland_frei_gb'] < 1.0:
        log(f"ALDI TALK: Inland-Volumen unter 1 GB ({status['inland_frei_gb']} GB) - versuche Nachbuchung.")
        aldi_book_free_gb(driver)
    else:
        log('ALDI TALK: Inland-Volumen ausreichend oder nicht auslesbar - keine Nachbuchung.')


def run_lidl(driver):
    log('--- LIDL CONNECT ---')
    if not LIDL_USER or not LIDL_PASS:
        log('LIDL CONNECT: Secrets nicht gesetzt, überspringe.')
        return
    if not lidl_login(driver):
        return
    status = lidl_read_status(driver)
    if status['inland_frei_gb'] is not None and status['inland_frei_gb'] < 1.0:
        log(f"LIDL CONNECT: Volumen unter 1 GB ({status['inland_frei_gb']} GB) - versuche Nachbuchung.")
        lidl_book_free_option(driver)
    else:
        log('LIDL CONNECT: Volumen ausreichend oder nicht auslesbar - keine Nachbuchung.')


def main():
    log('=== Multi-Provider Watcher gestartet ===')
    driver = build_driver()
    try:
        run_aldi(driver)
        run_lidl(driver)
    finally:
        driver.quit()
    log('=== Watcher beendet ===')


if __name__ == '__main__':
    main()
