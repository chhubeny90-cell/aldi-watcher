import os
import sys
import time
import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException, ElementNotInteractableException

# ===== KONFIGURATION =====
ALDI_USER = os.environ.get('ALDI_USER', '')
ALDI_PASS = os.environ.get('ALDI_PASS', '')
AUTO_BOOK_ENABLED = os.environ.get('AUTO_BOOK_ENABLED', 'true').lower() == 'true'

ALDI_LOGIN_URL = 'https://www.alditalk-kundenportal.de/portal/noauth/login'
ALDI_OVERVIEW_URL = 'https://www.alditalk-kundenportal.de/user/auth/account-overview/'
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


def login(driver) -> bool:
    if not ALDI_USER or not ALDI_PASS:
        log('FEHLER: ALDI_USER oder ALDI_PASS nicht gesetzt (Secrets fehlen).')
        return False
    try:
        driver.get(ALDI_LOGIN_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        dismiss_cookie_banner(driver)

        # Login-Formular: Felder haben dynamische IDs (input-5, input-6 etc.),
        # daher ueber Label/aria-label bzw. Feldreihenfolge suchen statt fester ID.
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

        # Anmelden-Button ist teils ein <a>-Link statt <button type=submit>
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
            # Fallback: Enter-Taste im Passwortfeld senden
            pass_field.send_keys(Keys.ENTER)

        wait.until(EC.any_of(
            EC.url_contains('uebersicht'),
            EC.url_contains('account-overview'),
        ))
        log('ALDI TALK: Login erfolgreich.')
        return True
    except TimeoutException:
        log('ALDI TALK: Login-Timeout - Login fehlgeschlagen oder Seite hat sich nicht wie erwartet veraendert.')
        try:
            driver.save_screenshot('login_timeout.png')
        except Exception:
            pass
        return False
    except NoSuchElementException as e:
        log(f'ALDI TALK: Login-Formular-Element nicht gefunden: {e}')
        return False
    except Exception as e:
        log(f'ALDI TALK: Unerwarteter Login-Fehler: {e}')
        return False


def read_status(driver) -> dict:
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
            import re
            m = re.search(r'(\d+[\.,]?\d*)\s*GB', text)
            if m:
                status['inland_frei_gb'] = float(m.group(1).replace(',', '.'))
        except NoSuchElementException:
            pass
        log(f'ALDI TALK Status: {status}')
        return status
    except TimeoutException:
        log('ALDI TALK: Timeout beim Laden der Uebersicht.')
        return status
    except Exception as e:
        log(f'ALDI TALK: Fehler beim Statusabruf: {e}')
        return status


def book_free_gb(driver) -> bool:
    if not AUTO_BOOK_ENABLED:
        log('Auto-Buchung deaktiviert (AUTO_BOOK_ENABLED=false) - keine Aktion.')
        return False
    try:
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        candidates = driver.find_elements(
            By.XPATH,
            "//*[contains(text(), '+1 GB') or contains(@aria-label, 'nachbuchen') or contains(text(), 'nachbuchen') or contains(text(), 'Highspeed')]"
        )
        clickable = [c for c in candidates if c.is_displayed() and c.is_enabled()]
        if not clickable:
            log('Keine aktive kostenlose Nachbuchoption gefunden (evtl. Schwelle noch nicht erreicht).')
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
        log('Kostenlose 1 GB Inland-Nachbuchung ausgeloest.')
        return True
    except Exception as e:
        log(f'Fehler beim Ausloesen der Nachbuchung: {e}')
        return False


def main():
    log('=== Aldi Watcher Check gestartet ===')
    driver = build_driver()
    try:
        if not login(driver):
            sys.exit(1)
        status = read_status(driver)
        if status['inland_frei_gb'] is not None and status['inland_frei_gb'] < 1.0:
            log(f"Inland-Volumen unter 1 GB ({status['inland_frei_gb']} GB) - versuche kostenlose Nachbuchung.")
            book_free_gb(driver)
        else:
            log('Inland-Volumen ausreichend oder nicht auslesbar - keine Nachbuchung noetig.')
    finally:
        driver.quit()
    log('=== Aldi Watcher Check beendet ===')


if __name__ == '__main__':
    main()
