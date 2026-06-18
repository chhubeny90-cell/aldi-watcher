import os
import time
import requests
from bs4 import BeautifulSoup

# ===== ALDI TALK =====
ALDI_USER = os.environ.get('ALDI_USER', '016312321869')
ALDI_PASS = os.environ.get('ALDI_PASS', '')

# ===== LIDL CONNECT =====
LIDL_USER = os.environ.get('LIDL_USER', '017452481970')
LIDL_PASS = os.environ.get('LIDL_PASS', '')

# ===== ALDI URLs =====
ALDI_LOGIN   = 'https://www.alditalk-kundenportal.de/portal/noauth/login'
ALDI_OVERVIEW = 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'
ALDI_BOOK    = 'https://www.alditalk-kundenportal.de/portal/auth/nachbuchung/'

# ===== LIDL URLs =====
LIDL_LOGIN    = 'https://kundenkonto.lidl-connect.de/login.html'
LIDL_OVERVIEW = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/uebersicht.html'
LIDL_REFILL   = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect/refill.html'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'de-DE,de;q=0.9',
}

# ============================================================
# ALDI TALK
# ============================================================
aldi_session = requests.Session()
aldi_session.headers.update(HEADERS)

def aldi_login():
    r = aldi_session.get(ALDI_LOGIN)
    soup = BeautifulSoup(r.text, 'html.parser')
    token = ''
    t = soup.find('input', {'name': '_csrf'})
    if t:
        token = t.get('value', '')
    resp = aldi_session.post(ALDI_LOGIN, data={
        'username': ALDI_USER,
        'password': ALDI_PASS,
        '_csrf': token,
    }, allow_redirects=True)
    ok = 'uebersicht' in resp.url or resp.status_code == 200
    print('[ALDI] Login', 'erfolgreich' if ok else 'FEHLGESCHLAGEN')
    return ok

def aldi_check():
    r = aldi_session.get(ALDI_OVERVIEW)
    if 'login' in r.url.lower():
        print('[ALDI] Session abgelaufen - re-login')
        aldi_login()
        return
    import re
    mb = re.findall(r'(\d+[,.]?\d*)\s*MB', r.text)
    gb = re.findall(r'(\d+[,.]?\d*)\s*GB', r.text)
    if mb:
        print(f'[ALDI] Unter 1 GB erkannt ({mb[0]} MB)! Buche +1 GB...')
        for i in range(5):
            book = aldi_session.post(ALDI_BOOK, data={'type': 'DATA_1GB'}, allow_redirects=True)
            print(f'[ALDI] Buchung {i+1}: Status {book.status_code}')
            time.sleep(1)
    else:
        print(f'[ALDI] Volumen OK (noch genug GB: {gb[:2]}), keine Buchung noetig')

# ============================================================
# LIDL CONNECT
# ============================================================
lidl_session = requests.Session()
lidl_session.headers.update(HEADERS)

def lidl_login():
    r = lidl_session.get(LIDL_LOGIN)
    soup = BeautifulSoup(r.text, 'html.parser')
    token = ''
    t = soup.find('input', {'name': '_csrf'}) or soup.find('input', {'name': 'csrf_token'})
    if t:
        token = t.get('value', '')
    resp = lidl_session.post(LIDL_LOGIN, data={
        'username': LIDL_USER,
        'password': LIDL_PASS,
        '_csrf': token,
    }, allow_redirects=True)
    ok = 'login' not in resp.url.lower()
    print('[LIDL] Login', 'erfolgreich' if ok else 'FEHLGESCHLAGEN')
    return ok

def lidl_check():
    r = lidl_session.get(LIDL_OVERVIEW)
    if 'login' in r.url.lower():
        print('[LIDL] Session abgelaufen - re-login')
        lidl_login()
        return
    import re
    mb = re.findall(r'(\d+[,.]?\d*)\s*MB', r.text)
    if mb or '0' in r.text:
        print(f'[LIDL] Unter 1 GB - aktiviere Refill...')
        refill = lidl_session.post(LIDL_REFILL, data={'action': 'refill'}, allow_redirects=True)
        print(f'[LIDL] Refill Status: {refill.status_code}')
    else:
        print('[LIDL] Volumen OK, keine Buchung noetig')

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    print('=== Aldi + Lidl Watcher gestartet ===')
    aldi_login()
    aldi_check()
    if LIDL_PASS:
        lidl_login()
        lidl_check()
    else:
        print('[LIDL] Kein Passwort gesetzt - uebersprungen')
