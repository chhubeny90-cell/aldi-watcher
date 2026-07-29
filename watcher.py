import os
import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# ===== KONFIGURATION =====
ALDI_USER = os.environ.get('ALDI_USER', '')
ALDI_PASS = os.environ.get('ALDI_PASS', '')
LIDL_USER = os.environ.get('LIDL_USER', '')
LIDL_PASS = os.environ.get('LIDL_PASS', '')
THRESHOLD_MB = int(os.environ.get('THRESHOLD_MB', 1000))
MAX_RETRIES = 5
CHECK_INTERVAL = 60  # Sekunden zwischen Checks
RUN_DURATION = 270  # Minuten Gesamtlaufzeit

# ===== ALDI TALK URLs =====
ALDI_LOGIN = 'https://www.alditalk-kundenportal.de/portal/noauth/login'
ALDI_OVERVIEW = 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'
ALDI_BOOK = 'https://www.alditalk-kundenportal.de/portal/auth/nachbuchung/'

# ===== LIDL CONNECT URLs =====
LIDL_LOGIN = 'https://kundenkonto.lidl-connect.de/login.html'
LIDL_OVERVIEW = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/uebersicht.html'
LIDL_REFILL = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/nachbuchung/'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 13; Pixel 7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Mobile Safari/537.36'
    ),
    'Accept-Language': 'de-DE,de;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Connection': 'keep-alive',
}


# ===== HILFSFUNKTIONEN =====
def log(msg: str):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] {msg}')


def parse_mb(text: str) -> float:
    """Konvertiert z.B. '2 GB', '500 MB', '1,5 GB' in MB (float)."""
    text = text.replace(',', '.').strip()
    m = re.search(r'([\d.]+)\s*(GB|MB)', text, re.IGNORECASE)
    if not m:
        return 0.0
    value, unit = float(m.group(1)), m.group(2).upper()
    return value * 1024 if unit == 'GB' else value


# ===== ALDI TALK =====
class AldiWatcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.logged_in = False

    def login(self) -> bool:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = self.session.get(ALDI_LOGIN, timeout=20)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'html.parser')
                csrf = ''
                tag = soup.find('input', {'name': '_csrf'})
                if tag:
                    csrf = tag.get('value', '')
                payload = {
                    'username': ALDI_USER,
                    'password': ALDI_PASS,
                    '_csrf': csrf,
                }
                r2 = self.session.post(ALDI_LOGIN, data=payload, timeout=20)
                if 'uebersicht' in r2.url or r2.status_code == 200:
                    self.logged_in = True
                    log('ALDI TALK: Login erfolgreich.')
                    return True
            except requests.RequestException as e:
                log(f'ALDI TALK: Login-Fehler (Versuch {attempt}/{MAX_RETRIES}): {e}')
            time.sleep(5 * attempt)
        log('ALDI TALK: Login fehlgeschlagen - alle Versuche ausgeschoepft.')
        return False

    def get_status(self) -> dict | None:
        """Liest Guthaben, Tarif und Restvolumen aus der Uebersichtsseite."""
        if not self.logged_in and not self.login():
            return None
        try:
            r = self.session.get(ALDI_OVERVIEW, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            guthaben_raw = ''
            g_tag = soup.find(string=re.compile(r'Guthaben', re.I))
            if g_tag and g_tag.parent:
                guthaben_raw = g_tag.parent.get_text(' ', strip=True)
            vol_inland_mb = 0.0
            vol_tags = soup.find_all(string=re.compile(r'\d+[.,]?\d*\s*(GB|MB)', re.I))
            for vt in vol_tags:
                val = parse_mb(vt)
                if val > 0:
                    vol_inland_mb = val
                    break
            tarif = ''
            t_tag = soup.find(string=re.compile(r'Tarif', re.I))
            if t_tag and t_tag.parent:
                tarif = t_tag.parent.get_text(' ', strip=True)
            status = {
                'guthaben': guthaben_raw,
                'tarif': tarif,
                'vol_inland_mb': vol_inland_mb,
            }
            log(f'ALDI TALK Status: {status}')
            return status
        except requests.RequestException as e:
            log(f'ALDI TALK: Fehler beim Abruf: {e}')
            self.logged_in = False
            return None

    def check_and_alert(self):
        status = self.get_status()
        if status and status['vol_inland_mb'] < THRESHOLD_MB:
            log(
                f'WARNUNG: ALDI TALK Restvolumen unter Schwellwert! '
                f'{status["vol_inland_mb"]:.0f} MB < {THRESHOLD_MB} MB'
            )


# ===== LIDL CONNECT =====
class LidlWatcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.logged_in = False

    def login(self) -> bool:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = self.session.get(LIDL_LOGIN, timeout=20)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'html.parser')
                csrf = ''
                tag = soup.find('input', {'name': '_token'}) or soup.find('input', {'name': 'csrf_token'})
                if tag:
                    csrf = tag.get('value', '')
                payload = {
                    'username': LIDL_USER,
                    'password': LIDL_PASS,
                    '_token': csrf,
                }
                r2 = self.session.post(LIDL_LOGIN, data=payload, timeout=20)
                if 'uebersicht' in r2.url or r2.status_code == 200:
                    self.logged_in = True
                    log('LIDL CONNECT: Login erfolgreich.')
                    return True
            except requests.RequestException as e:
                log(f'LIDL CONNECT: Login-Fehler (Versuch {attempt}/{MAX_RETRIES}): {e}')
            time.sleep(5 * attempt)
        log('LIDL CONNECT: Login fehlgeschlagen.')
        return False

    def get_status(self) -> dict | None:
        if not self.logged_in and not self.login():
            return None
        try:
            r = self.session.get(LIDL_OVERVIEW, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            vol_mb = 0.0
            vol_tags = soup.find_all(string=re.compile(r'\d+[.,]?\d*\s*(GB|MB)', re.I))
            for vt in vol_tags:
                val = parse_mb(vt)
                if val > 0:
                    vol_mb = val
                    break
            status = {'vol_mb': vol_mb}
            log(f'LIDL CONNECT Status: {status}')
            return status
        except requests.RequestException as e:
            log(f'LIDL CONNECT: Fehler beim Abruf: {e}')
            self.logged_in = False
            return None

    def check_and_alert(self):
        status = self.get_status()
        if status and status['vol_mb'] < THRESHOLD_MB:
            log(
                f'WARNUNG: LIDL CONNECT Restvolumen unter Schwellwert! '
                f'{status["vol_mb"]:.0f} MB < {THRESHOLD_MB} MB'
            )


# ===== MAIN LOOP =====
def main():
    log('=== Aldi/Lidl Watcher gestartet ===')
    log(f'Laufzeit: {RUN_DURATION} min | Interval: {CHECK_INTERVAL} s | Schwellwert: {THRESHOLD_MB} MB')
    aldi = AldiWatcher()
    lidl = LidlWatcher()
    end_time = time.time() + RUN_DURATION * 60
    while time.time() < end_time:
        log('--- Neuer Check-Zyklus ---')
        aldi.check_and_alert()
        lidl.check_and_alert()
        remaining = end_time - time.time()
        if remaining <= 0:
            break
        sleep_time = min(CHECK_INTERVAL, remaining)
        log(f'Naechster Check in {sleep_time:.0f} Sekunden...')
        time.sleep(sleep_time)
    log('=== Watcher beendet ===')


if __name__ == '__main__':
    main()
