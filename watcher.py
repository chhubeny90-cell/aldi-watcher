import os
import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

# ===== KONFIGURATION =====
ALDI_USER = os.environ.get('ALDI_USER', '016312321869')
ALDI_PASS = os.environ.get('ALDI_PASS', '')
LIDL_USER = os.environ.get('LIDL_USER', '01745248197')
LIDL_PASS = os.environ.get('LIDL_PASS', '')

THRESHOLD_MB = 1000  # Buchung wenn unter 1 GB
MAX_RETRIES   = 5

# ===== ALDI URLs (kundenportal) =====
ALDI_LOGIN    = 'https://www.alditalk-kundenportal.de/portal/noauth/login'
ALDI_OVERVIEW = 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'
ALDI_BOOK     = 'https://www.alditalk-kundenportal.de/portal/auth/nachbuchung/'

# ===== LIDL URLs =====
LIDL_LOGIN    = 'https://kundenkonto.lidl-connect.de/login.html'
LIDL_OVERVIEW = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/uebersicht.html'
LIDL_REFILL   = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/nachbuchung/'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/124.0.0.0 Mobile Safari/537.36',
    'Accept-Language': 'de-DE,de;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Connection': 'keep-alive',
}

def log(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open('aldi_watcher.log', 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def to_mb(value_str, unit_str):
    try:
        val = float(value_str.replace(',', '.').strip())
        unit = unit_str.strip().upper()
        if 'GB' in unit:
            return val * 1000
        elif 'MB' in unit:
            return val
        elif 'KB' in unit:
            return val / 1000
    except:
        pass
    return None

def extract_mb_from_text(text):
    gb_vals = [float(v.replace(',', '.')) * 1000
               for v in re.findall(r'(\d+[,.]?\d*)\s*GB', text)]
    mb_vals = [float(v.replace(',', '.'))
               for v in re.findall(r'(\d+[,.]?\d*)\s*MB', text)]
    all_vals = gb_vals + mb_vals
    return min(all_vals) if all_vals else None

def wartung_check(text, provider):
    """Gibt True zurueck wenn Provider in Wartung ist."""
    wartung_keywords = ['wartung', 'maintenance', 'maintenance page', 'wartungsseite']
    text_lower = text.lower()
    if any(k in text_lower for k in wartung_keywords):
        log(f'[{provider}] WARTUNG aktiv - ueberspringe Zyklus')
        return True
    return False

# ============================================================
# ALDI TALK
# ============================================================
aldi_session = requests.Session()
aldi_session.headers.update(HEADERS)

def aldi_get_csrf(url):
    try:
        r = aldi_session.get(url, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        for name in ['_csrf', 'csrf_token', '_csrf_token']:
            t = soup.find('input', {'name': name})
            if t:
                return t.get('value', ''), r
        return '', r
    except Exception as e:
        log(f'[ALDI] CSRF-Fehler: {e}')
        return '', None

def aldi_login():
    try:
        csrf, r = aldi_get_csrf(ALDI_LOGIN)
        if r is None:
            return False
        if wartung_check(r.text, 'ALDI'):
            return False
        resp = aldi_session.post(ALDI_LOGIN, data={
            'username': ALDI_USER,
            'password': ALDI_PASS,
            '_csrf': csrf,
        }, allow_redirects=True, timeout=30)
        ok = 'uebersicht' in resp.url or 'auth' in resp.url
        log(f'[ALDI] Login {"erfolgreich" if ok else "FEHLGESCHLAGEN"} (HTTP {resp.status_code}, URL: {resp.url[:80]})')
        if not ok:
            log(f'[ALDI] Seite: {resp.text[:300]}')
        return ok
    except Exception as e:
        log(f'[ALDI] Login-Fehler: {e}')
        return False

def aldi_check():
    try:
        r = aldi_session.get(ALDI_OVERVIEW, timeout=30)
        if wartung_check(r.text, 'ALDI'):
            return
        if 'login' in r.url.lower() or r.status_code == 401:
            log('[ALDI] Session abgelaufen - re-login...')
            if not aldi_login():
                log('[ALDI] Re-login fehlgeschlagen')
                return
            r = aldi_session.get(ALDI_OVERVIEW, timeout=30)
        log(f'[ALDI] Uebersicht (HTTP {r.status_code}, URL: {r.url[:80]})')
        soup = BeautifulSoup(r.text, 'html.parser')
        page_text = soup.get_text(' ')
        mb = extract_mb_from_text(page_text)
        if mb is None:
            log('[ALDI] Kein Volumen gefunden. Seite (500 Zeichen):')
            log(r.text[:500])
            return
        log(f'[ALDI] Aktuelles Volumen: {mb:.1f} MB ({mb/1000:.2f} GB)')
        if mb < THRESHOLD_MB:
            log(f'[ALDI] Unter {THRESHOLD_MB} MB! Starte Buchungen...')
            csrf2, _ = aldi_get_csrf(ALDI_BOOK)
            for i in range(1, MAX_RETRIES + 1):
                try:
                    book = aldi_session.post(ALDI_BOOK, data={
                        'type': 'DATA_1GB',
                        '_csrf': csrf2,
                    }, allow_redirects=True, timeout=30)
                    log(f'[ALDI] Buchung {i}/{MAX_RETRIES}: HTTP {book.status_code}')
                    if book.status_code == 200 and 'error' not in book.url.lower():
                        log('[ALDI] +1 GB erfolgreich gebucht!')
                        break
                except Exception as e:
                    log(f'[ALDI] Buchungs-Fehler {i}: {e}')
                time.sleep(2)
        else:
            log(f'[ALDI] Volumen OK ({mb:.1f} MB), keine Buchung noetig')
    except Exception as e:
        log(f'[ALDI] Fehler: {e}')

# ============================================================
# LIDL CONNECT
# ============================================================
lidl_session = requests.Session()
lidl_session.headers.update(HEADERS)

def lidl_login():
    try:
        r = lidl_session.get(LIDL_LOGIN, timeout=30)
        if wartung_check(r.text, 'LIDL'):
            return False
        soup = BeautifulSoup(r.text, 'html.parser')
        token = ''
        for name in ['_csrf', 'csrf_token', 'token', '__RequestVerificationToken']:
            t = soup.find('input', {'name': name})
            if t:
                token = t.get('value', '')
                break
        meta = soup.find('meta', {'name': 'csrf-token'})
        if meta and not token:
            token = meta.get('content', '')
        form = soup.find('form')
        action = LIDL_LOGIN
        if form and form.get('action'):
            a = form['action']
            action = a if a.startswith('http') else 'https://kundenkonto.lidl-connect.de' + a
        log(f'[LIDL] Login POST -> {action} (CSRF: {"ja" if token else "nein"})')
        resp = lidl_session.post(action, data={
            'username': LIDL_USER,
            'password': LIDL_PASS,
            '_csrf': token,
        }, allow_redirects=True, timeout=30)
        ok = 'login' not in resp.url.lower() and resp.status_code == 200
        log(f'[LIDL] Login {"erfolgreich" if ok else "FEHLGESCHLAGEN"} (HTTP {resp.status_code})')
        if not ok:
            log(f'[LIDL] Response: {resp.text[:200]}')
        return ok
    except Exception as e:
        log(f'[LIDL] Login-Fehler: {e}')
        return False

def lidl_check():
    try:
        r = lidl_session.get(LIDL_OVERVIEW, timeout=30)
        if wartung_check(r.text, 'LIDL'):
            return
        if 'login' in r.url.lower() or r.status_code in (401, 403):
            log('[LIDL] Session abgelaufen - re-login...')
            if not lidl_login():
                return
            r = lidl_session.get(LIDL_OVERVIEW, timeout=30)
        log(f'[LIDL] Uebersicht (HTTP {r.status_code}, URL: {r.url[:80]})')
        soup = BeautifulSoup(r.text, 'html.parser')
        mb = extract_mb_from_text(soup.get_text(' '))
        if mb is None:
            log('[LIDL] Kein Volumen gefunden:')
            log(r.text[:500])
            return
        log(f'[LIDL] Aktuelles Volumen: {mb:.1f} MB ({mb/1000:.2f} GB)')
        if mb < THRESHOLD_MB:
            log(f'[LIDL] Unter {THRESHOLD_MB} MB! Starte Nachbuchung...')
            for i in range(1, MAX_RETRIES + 1):
                try:
                    refill = lidl_session.post(LIDL_REFILL, data={
                        'action': 'refill', 'type': 'DATA_1GB',
                    }, allow_redirects=True, timeout=30)
                    log(f'[LIDL] Nachbuchung {i}/{MAX_RETRIES}: HTTP {refill.status_code}')
                    if refill.status_code == 200:
                        log('[LIDL] Nachbuchung erfolgreich!')
                        break
                    elif refill.status_code >= 500:
                        time.sleep(10)
                except Exception as e:
                    log(f'[LIDL] Fehler {i}: {e}')
                    time.sleep(5)
        else:
            log(f'[LIDL] Volumen OK ({mb:.1f} MB), keine Buchung noetig')
    except Exception as e:
        log(f'[LIDL] Fehler: {e}')

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    log('=== Aldi + Lidl Watcher gestartet ===')
    log(f'Schwellwert: {THRESHOLD_MB} MB | Max Versuche: {MAX_RETRIES}')

    if ALDI_PASS:
        aldi_login()
        aldi_check()
    else:
        log('[ALDI] Kein Passwort (ALDI_PASS) - uebersprungen')

    if LIDL_PASS:
        lidl_login()
        lidl_check()
    else:
        log('[LIDL] Kein Passwort (LIDL_PASS) - uebersprungen')

    log('=== Watcher-Lauf abgeschlossen ===')
