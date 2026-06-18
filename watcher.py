import os
import time
import requests
from bs4 import BeautifulSoup

ALDI_USER = os.environ.get('ALDI_USER', '016312321869')
ALDI_PASS = os.environ.get('ALDI_PASS', '')

LOGIN_URL = 'https://www.alditalk-kundenportal.de/portal/noauth/login'
OVERVIEW_URL = 'https://www.alditalk-kundenportal.de/portal/auth/uebersicht/'
BOOK_URL = 'https://www.alditalk-kundenportal.de/portal/auth/nachbuchung/'

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'de-DE,de;q=0.9',
})

def login():
    r = session.get(LOGIN_URL)
    soup = BeautifulSoup(r.text, 'html.parser')
    token = ''
    t = soup.find('input', {'name': '_csrf'})
    if t:
        token = t.get('value', '')
    data = {
        'username': ALDI_USER,
        'password': ALDI_PASS,
        '_csrf': token,
    }
    resp = session.post(LOGIN_URL, data=data, allow_redirects=True)
    if 'uebersicht' in resp.url or resp.status_code == 200:
        print('[ALDI] Login erfolgreich')
        return True
    print('[ALDI] Login fehlgeschlagen')
    return False

def check_and_book():
    r = session.get(OVERVIEW_URL)
    soup = BeautifulSoup(r.text, 'html.parser')
    text = r.text
    # Volumen unter 1 GB prüfen (MB-Anzeige = unter 1 GB)
    if 'MB' in text and 'Inland' in text:
        print('[ALDI] Unter 1 GB erkannt! Buche +1 GB...')
        # Mehrfach buchen
        for i in range(5):
            try:
                book = session.post(BOOK_URL, data={'type': 'DATA_1GB'}, allow_redirects=True)
                print(f'[ALDI] Buchung {i+1}: Status {book.status_code}')
                time.sleep(1)
            except Exception as e:
                print(f'[ALDI] Fehler: {e}')
    else:
        import re
        gb = re.findall(r'([\d,\.]+)\s*GB', text)
        print(f'[ALDI] Volumen OK (noch genug GB: {gb[:2]}), keine Buchung noetig')

if __name__ == '__main__':
    if login():
        check_and_book()
    else:
        print('[ALDI] Nicht eingeloggt - Passwort pruefen!')
