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

THRESHOLD_MB  = 1000
MAX_RETRIES   = 5
CHECK_INTERVAL = 60
RUN_DURATION   = 270

# ===== ALDI URLs =====
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

def extract_mb_from_text(text):
    gb_vals = [float(v.replace(',', '.')) * 1000
               for v in re.findall(r'(\d+[,.]?\d*)\s*GB', text)]
    mb_vals = [float(v.replace(',', '.'))
               for v in re.findall(r'(\d+[,.]?\d*)\s*MB', text)]
    all_vals = gb_vals + mb_vals
    return min(all_vals) if all_vals else None

def wartung_check(text, provider):
    keywords = ['wartung', 'maintenance', 'wartungsseite']
    if any(k in text.lower() for k in keywords):
        log(f'[{provider}] WARTUNG aktiv - ueberspringe')
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
        if r is None or wartung_check(r.text, 'ALDI'):
            return False
        resp = aldi_session.post(ALDI_LOGIN, data={
            'username': ALDI_USER,
            'password': ALDI_PASS,
            '_csrf': csrf,
        }, allow_redirects=True, timeout=30)
        ok = 'uebersicht' in resp.url or 'auth' in resp.url
        log(f'[ALDI] Login {"erfolgreich" if ok else "FEHLGESCHLAGEN"} (HTTP {resp.status_code})')
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
                return
            r = aldi_session.get(ALDI_OVERVIEW, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        mb = extract_mb_from_text(soup.get_text(' '))
        if mb is None:
            log(f'[ALDI] Kein Volumen gefunden (HTTP {r.status_code})')
            log(r.text[:300])
            return
        log(f'[ALDI] Volumen: {mb:.1f} MB ({mb/1000:.2f} GB)')
        if mb < THRESHOLD_MB:
            log(f'[ALDI] UNTER {THRESHOLD_MB} MB! Buche +1 GB...')
            csrf2, _ = aldi_get_csrf(ALDI_BOOK)
            for i in range(1, MAX_RETRIES + 1):
                try:
                    book = aldi_session.post(ALDI_BOOK, data={
                        'type': 'DATA_1GB', '_csrf': csrf2,
                    }, allow_redirects=True, timeout=30)
                    log(f'[ALDI] Buchung {i}: HTTP {book.status_code}')
                    if book.status_code == 200 and 'error' not in book.url.lower():
                        log('[ALDI] +1 GB erfolgreich gebucht!')
                        break
                except Exception as e:
                    log(f'[ALDI] Buchungs-Fehler {i}: {e}')
                time.sleep(2)
        else:
            log('[ALDI] OK - keine Buchung noetig')
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
        resp = lidl_session.post(action, data={
            'username': LIDL_USER, 'password': LIDL_PASS, '_csrf': token,
        }, allow_redirects=True, timeout=30)
        ok = 'login' not in resp.url.lower() and resp.status_code == 200
        log(f'[LIDL] Login {"erfolgreich" if ok else "FEHLGESCHLAGEN"} (HTTP {resp.status_code})')
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
        soup = BeautifulSoup(r.text, 'html.parser')
        mb = extract_mb_from_text(soup.get_text(' '))
        if mb is None:
            log(f'[LIDL] Kein Volumen gefunden (HTTP {r.status_code})')
            return
        log(f'[LIDL] Volumen: {mb:.1f} MB ({mb/1000:.2f} GB)')
        if mb < THRESHOLD_MB:
            log('[LIDL] UNTER Schwellwert! Buche nach...')
            for i in range(1, MAX_RETRIES + 1):
                try:
                    refill = lidl_session.post(LIDL_REFILL, data={
                        'action': 'refill', 'type': 'DATA_1GB',
                    }, allow_redirects=True, timeout=30)
                    log(f'[LIDL] Nachbuchung {i}: HTTP {refill.status_code}')
                    if refill.status_code == 200:
                        log('[LIDL] Nachbuchung erfolgreich!')
                        break
                    elif refill.status_code >= 500:
                        time.sleep(10)
                except Exception as e:
                    log(f'[LIDL] Fehler {i}: {e}')
                    time.sleep(5)
        else:
            log('[LIDL] OK - keine Buchung noetig')
    except Exception as e:
        log(f'[LIDL] Fehler: {e}')

# ============================================================
# MAIN - prueft alle 60s, laeuft 4.5 Min, nahtlos mit 5-Min-Cron
# ============================================================
if __name__ == '__main__':
    log('=== Aldi + Lidl Watcher gestartet ===')
    log(f'Intervall: {CHECK_INTERVAL}s | Laufzeit: {RUN_DURATION}s | Schwelle: {THRESHOLD_MB} MB')

    if ALDI_PASS:
        aldi_login()
    if LIDL_PASS:
        lidl_login()

    start_time = time.time()
    runde = 0

    while time.time() - start_time < RUN_DURATION:
        runde += 1
        log(f'--- Runde {runde} ---')
        if ALDI_PASS:
            aldi_check()
        else:
            log('[ALDI] Kein Passwort - uebersprungen')
        if LIDL_PASS:
            lidl_check()
        else:
            log('[LIDL] Kein Passwort - uebersprungen')
        verbleibend = RUN_DURATION - (time.time() - start_time)
        if verbleibend > CHECK_INTERVAL:
            log(f'Warte {CHECK_INTERVAL}s...')
            time.sleep(CHECK_INTERVAL)
        else:
            break

    log('=== Watcher-Lauf abgeschlossen ===')
