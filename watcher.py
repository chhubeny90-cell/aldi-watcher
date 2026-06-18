import os
import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# ===== KONFIGURATION =====
ALDI_USER = os.environ.get('ALDI_USER', '016312321869')
ALDI_PASS = os.environ.get('ALDI_PASS', '')
LIDL_USER = os.environ.get('LIDL_USER', '017452481970')
LIDL_PASS = os.environ.get('LIDL_PASS', '')

THRESHOLD_MB = 1000  # Buchung wenn unter 1 GB (1000 MB)
MAX_RETRIES   = 5
INTERVAL_SEC  = 1800  # 30 Minuten (nur fuer lokalen Dauerbetrieb)

# ===== ALDI URLs =====
ALDI_LOGIN    = 'https://www.alditalk-kundenportal.de/portal/noauth/login'
ALDI_OVERVIEW = 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'
ALDI_BOOK     = 'https://www.alditalk-kundenportal.de/portal/auth/nachbuchung/'

# ===== LIDL URLs =====
LIDL_LOGIN    = 'https://kundenkonto.lidl-connect.de/login.html'
LIDL_OVERVIEW = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/uebersicht.html'
LIDL_REFILL   = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/nachbuchung/'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/124.0 Safari/537.36',
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

def log(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open('aldi_watcher.log', 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def extract_mb(text):
    """Gibt den niedrigsten gefundenen MB-Wert zurueck (0 wenn keiner)."""
    gb_vals = [float(v.replace(',', '.')) * 1000
               for v in re.findall(r'(\d+[,.]?\d*)\s*GB', text)]
    mb_vals = [float(v.replace(',', '.'))
               for v in re.findall(r'(\d+[,.]?\d*)\s*MB', text)]
    all_vals = gb_vals + mb_vals
    return min(all_vals) if all_vals else None

# ============================================================
# ALDI TALK
# ============================================================
aldi_session = requests.Session()
aldi_session.headers.update(HEADERS)

def aldi_login():
    try:
        r = aldi_session.get(ALDI_LOGIN, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        token = ''
        t = soup.find('input', {'name': '_csrf'})
        if t:
            token = t.get('value', '')
        resp = aldi_session.post(ALDI_LOGIN, data={
            'username': ALDI_USER,
            'password': ALDI_PASS,
            '_csrf': token,
        }, allow_redirects=True, timeout=30)
        ok = 'uebersicht' in resp.url or 'auth' in resp.url
        log(f'[ALDI] Login {"erfolgreich" if ok else "FEHLGESCHLAGEN"} (HTTP {resp.status_code})')
        return ok
    except Exception as e:
        log(f'[ALDI] Login-Fehler: {e}')
        return False

def aldi_get_csrf(url):
    r = aldi_session.get(url, timeout=30)
    soup = BeautifulSoup(r.text, 'html.parser')
    t = soup.find('input', {'name': '_csrf'})
    return t.get('value', '') if t else ''

def aldi_check():
    try:
        r = aldi_session.get(ALDI_OVERVIEW, timeout=30)
        if 'login' in r.url.lower() or r.status_code == 401:
            log('[ALDI] Session abgelaufen - re-login...')
            if not aldi_login():
                log('[ALDI] Re-login fehlgeschlagen, ueberspringe Zyklus')
                return
            r = aldi_session.get(ALDI_OVERVIEW, timeout=30)
        mb = extract_mb(r.text)
        if mb is None:
            log('[ALDI] Kein Datenvolumen auf Seite gefunden - HTML-Struktur evtl. geaendert')
            log(f'[ALDI] Response-Ausschnitt: {r.text[:500]}')
            return
        log(f'[ALDI] Aktuelles Volumen: {mb:.0f} MB')
        if mb < THRESHOLD_MB:
            log(f'[ALDI] Unter {THRESHOLD_MB} MB! Starte Buchungen...')
            for i in range(1, MAX_RETRIES + 1):
                try:
                    csrf = aldi_get_csrf(ALDI_BOOK)
                    book = aldi_session.post(ALDI_BOOK, data={
                        'type': 'DATA_1GB',
                        '_csrf': csrf,
                    }, allow_redirects=True, timeout=30)
                    log(f'[ALDI] Buchung {i}/{MAX_RETRIES}: HTTP {book.status_code}')
                    if book.status_code == 200 and 'error' not in book.url.lower():
                        log('[ALDI] Buchung erfolgreich!')
                        break
                except Exception as e:
                    log(f'[ALDI] Buchungs-Fehler Versuch {i}: {e}')
                time.sleep(2)
        else:
            log(f'[ALDI] Volumen OK ({mb:.0f} MB), keine Buchung noetig')
    except Exception as e:
        log(f'[ALDI] Fehler in aldi_check: {e}')

# ============================================================
# LIDL CONNECT
# ============================================================
lidl_session = requests.Session()
lidl_session.headers.update(HEADERS)

def lidl_login():
    try:
        r = lidl_session.get(LIDL_LOGIN, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        token = ''
        for name in ['_csrf', 'csrf_token', 'token', '__RequestVerificationToken']:
            t = soup.find('input', {'name': name})
            if t:
                token = t.get('value', '')
                break
        # Auch in Meta-Tags suchen
        meta = soup.find('meta', {'name': 'csrf-token'})
        if meta and not token:
            token = meta.get('content', '')
        resp = lidl_session.post(LIDL_LOGIN, data={
            'username': LIDL_USER,
            'password': LIDL_PASS,
            '_csrf': token,
        }, allow_redirects=True, timeout=30)
        ok = 'login' not in resp.url.lower() and resp.status_code == 200
        log(f'[LIDL] Login {"erfolgreich" if ok else "FEHLGESCHLAGEN"} (HTTP {resp.status_code}, URL: {resp.url[:80]})')
        return ok
    except Exception as e:
        log(f'[LIDL] Login-Fehler: {e}')
        return False

def lidl_check():
    try:
        r = lidl_session.get(LIDL_OVERVIEW, timeout=30)
        if 'login' in r.url.lower() or r.status_code in (401, 403):
            log('[LIDL] Session abgelaufen - re-login...')
            if not lidl_login():
                log('[LIDL] Re-login fehlgeschlagen, ueberspringe Zyklus')
                return
            r = lidl_session.get(LIDL_OVERVIEW, timeout=30)
        mb = extract_mb(r.text)
        if mb is None:
            log('[LIDL] Kein Datenvolumen auf Seite gefunden')
            log(f'[LIDL] Response-Ausschnitt: {r.text[:500]}')
            return
        log(f'[LIDL] Aktuelles Volumen: {mb:.0f} MB')
        if mb < THRESHOLD_MB:
            log(f'[LIDL] Unter {THRESHOLD_MB} MB! Starte Nachbuchung...')
            for i in range(1, MAX_RETRIES + 1):
                try:
                    refill = lidl_session.post(LIDL_REFILL, data={
                        'action': 'refill',
                        'type': 'DATA_1GB',
                    }, allow_redirects=True, timeout=30)
                    log(f'[LIDL] Nachbuchung {i}/{MAX_RETRIES}: HTTP {refill.status_code}')
                    if refill.status_code == 200:
                        log('[LIDL] Nachbuchung erfolgreich!')
                        break
                    elif refill.status_code >= 500:
                        log(f'[LIDL] Server-Fehler ({refill.status_code}), warte 10s...')
                        time.sleep(10)
                except Exception as e:
                    log(f'[LIDL] Buchungs-Fehler Versuch {i}: {e}')
                    time.sleep(5)
        else:
            log(f'[LIDL] Volumen OK ({mb:.0f} MB), keine Buchung noetig')
    except Exception as e:
        log(f'[LIDL] Fehler in lidl_check: {e}')

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    log('=== Aldi + Lidl Watcher gestartet ===')
    log(f'Schwellwert: {THRESHOLD_MB} MB | Max Versuche: {MAX_RETRIES}')

    # ALDI TALK
    if ALDI_PASS:
        aldi_login()
        aldi_check()
    else:
        log('[ALDI] Kein Passwort gesetzt (ALDI_PASS) - uebersprungen')

    # LIDL CONNECT
    if LIDL_PASS:
        lidl_login()
        lidl_check()
    else:
        log('[LIDL] Kein Passwort gesetzt (LIDL_PASS) - uebersprungen')

    log('=== Watcher-Lauf abgeschlossen ===')
