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

THRESHOLD_MB = 1000  # Buchung wenn unter 1 GB
MAX_RETRIES   = 5

# ===== ALDI URLs (alditalk-kundenbetreuung.de) =====
ALDI_BASE     = 'https://www.alditalk-kundenbetreuung.de/de'
ALDI_LOGIN    = 'https://www.alditalk-kundenbetreuung.de/de/login_check'
ALDI_OVERVIEW = 'https://www.alditalk-kundenbetreuung.de/de/konto/kontoubersicht'
ALDI_BOOK     = 'https://www.alditalk-kundenportal.de/portal/auth/nachbuchung/'

# ===== LIDL URLs =====
LIDL_LOGIN    = 'https://kundenkonto.lidl-connect.de/login.html'
LIDL_OVERVIEW = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/uebersicht.html'
LIDL_REFILL   = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/nachbuchung/'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
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
    """Konvertiert Volumen-Angaben in MB."""
    try:
        val = float(value_str.replace(',', '.').replace('\xa0', ''))
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
    """Findet den kleinsten MB-Wert im Text (fallback fuer beliebige HTML)."""
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

def aldi_get_csrf(url):
    r = aldi_session.get(url, timeout=30)
    soup = BeautifulSoup(r.text, 'html.parser')
    for name in ['_csrf_token', '_csrf', 'csrf_token']:
        t = soup.find('input', {'name': name})
        if t:
            return t.get('value', ''), r
    return '', r

def aldi_login():
    try:
        csrf, r = aldi_get_csrf(ALDI_BASE)
        resp = aldi_session.post(ALDI_LOGIN, data={
            '_username': ALDI_USER,
            '_password': ALDI_PASS,
            '_csrf_token': csrf,
        }, allow_redirects=True, timeout=30)
        ok = 'login' not in resp.url.lower() and resp.status_code == 200
        log(f'[ALDI] Login {"erfolgreich" if ok else "FEHLGESCHLAGEN"} (HTTP {resp.status_code}, URL: {resp.url[:70]})')
        return ok
    except Exception as e:
        log(f'[ALDI] Login-Fehler: {e}')
        return False

def aldi_parse_volume(html):
    """Parst das Datenvolumen aus der Aldi-Kundenbetreuung Seite."""
    soup = BeautifulSoup(html, 'html.parser')
    # Suche nach Volumen-Elementen (verschiedene CSS-Klassen moegich)
    for cls in ['egn-free', 'data-volume', 'volume', 'volumen']:
        elems = soup.find_all(class_=re.compile(cls, re.I))
        for e in elems:
            txt = e.get_text(' ', strip=True)
            m = re.search(r'(\d+[,.]?\d*)\s*(GB|MB|KB)', txt, re.I)
            if m:
                mb = to_mb(m.group(1), m.group(2))
                if mb is not None:
                    return mb
    # Fallback: ganzen Text durchsuchen
    return extract_mb_from_text(soup.get_text())

def aldi_check():
    try:
        r = aldi_session.get(ALDI_OVERVIEW, timeout=30)
        if 'login' in r.url.lower() or r.status_code in (401, 403):
            log('[ALDI] Session abgelaufen - re-login...')
            if not aldi_login():
                log('[ALDI] Re-login fehlgeschlagen, ueberspringe Zyklus')
                return
            r = aldi_session.get(ALDI_OVERVIEW, timeout=30)
        log(f'[ALDI] Uebersicht geladen (HTTP {r.status_code}, URL: {r.url[:70]})')
        mb = aldi_parse_volume(r.text)
        if mb is None:
            log('[ALDI] Kein Datenvolumen gefunden - HTML Ausschnitt (500 Zeichen):')
            log(r.text[:500])
            return
        log(f'[ALDI] Aktuelles Volumen: {mb:.1f} MB ({mb/1000:.2f} GB)')
        if mb < THRESHOLD_MB:
            log(f'[ALDI] Unter Schwellwert ({THRESHOLD_MB} MB)! Starte Buchungen...')
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
                    log(f'[ALDI] Buchungs-Fehler Versuch {i}: {e}')
                time.sleep(2)
        else:
            log(f'[ALDI] Volumen OK ({mb:.1f} MB), keine Buchung noetig')
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
        for name in ['_csrf', 'csrf_token', 'token', '__RequestVerificationToken',
                     'authenticity_token']:
            t = soup.find('input', {'name': name})
            if t:
                token = t.get('value', '')
                break
        meta = soup.find('meta', {'name': 'csrf-token'})
        if meta and not token:
            token = meta.get('content', '')
        # Formular-Action URL ermitteln
        form = soup.find('form')
        action = LIDL_LOGIN
        if form and form.get('action'):
            action = form['action']
            if not action.startswith('http'):
                action = 'https://kundenkonto.lidl-connect.de' + action
        log(f'[LIDL] Login POST an: {action} (token: {"ja" if token else "nein"})')
        resp = lidl_session.post(action, data={
            'username': LIDL_USER,
            'password': LIDL_PASS,
            '_csrf': token,
            'j_username': LIDL_USER,
            'j_password': LIDL_PASS,
        }, allow_redirects=True, timeout=30)
        ok = 'login' not in resp.url.lower() and resp.status_code == 200
        log(f'[LIDL] Login {"erfolgreich" if ok else "FEHLGESCHLAGEN"} (HTTP {resp.status_code}, URL: {resp.url[:80]})')
        if not ok:
            log(f'[LIDL] Response Ausschnitt: {resp.text[:300]}')
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
        log(f'[LIDL] Uebersicht geladen (HTTP {r.status_code}, URL: {r.url[:70]})')
        mb = extract_mb_from_text(r.text)
        if mb is None:
            log('[LIDL] Kein Datenvolumen gefunden - HTML Ausschnitt:')
            log(r.text[:500])
            return
        log(f'[LIDL] Aktuelles Volumen: {mb:.1f} MB ({mb/1000:.2f} GB)')
        if mb < THRESHOLD_MB:
            log(f'[LIDL] Unter Schwellwert! Starte Nachbuchung...')
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
            log(f'[LIDL] Volumen OK ({mb:.1f} MB), keine Buchung noetig')
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
