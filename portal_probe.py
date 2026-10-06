"""Credential-free diagnosis of public login pages; never submit a form."""
import json
import os
import re
import time
from urllib.parse import urlsplit

from selenium.webdriver.common.by import By
from watcher import build_driver, ALDI_LOGIN_URL, LIDL_LOGIN_URL
from monitoring import write_report, utcnow


def host(url):
    value = urlsplit(url).hostname or ''
    return value if re.fullmatch(r'[a-z0-9.-]{1,100}', value) else 'redacted'


def error_categories(message):
    patterns = {
        'csp': r'content security policy|refused to (?:load|execute|connect)',
        'cors': r'cross-origin|cors policy',
        'reference_error': r'ReferenceError',
        'type_error': r'TypeError',
        'syntax_error': r'SyntaxError',
        'network_blocked': r'ERR_BLOCKED|ERR_ACCESS_DENIED',
        'network_failed': r'ERR_FAILED|ERR_CONNECTION|ERR_NAME_NOT_RESOLVED',
        'http_403': r'403|Forbidden',
        'http_404': r'404|Not Found',
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, message, re.I)] or ['other']


def probe(name, url):
    result = {'provider': name, 'started_at': utcnow(), 'status': 'failed'}
    driver = None
    try:
        driver = build_driver()
        driver.get(url)
        time.sleep(8)  # Allow the public SPA to render; no interaction or retries.
        result['host'] = host(driver.current_url)
        result['ready_state'] = driver.execute_script('return document.readyState')
        fields = driver.find_elements(By.CSS_SELECTOR, 'input')
        result['visible_input_types'] = [
            kind if kind in {'text', 'tel', 'email', 'password', 'checkbox', 'submit', 'button', 'search'} else 'other'
            for element in fields if element.is_displayed()
            for kind in [element.get_attribute('type')]
        ]
        result['frames'] = [{'host': host(f.get_attribute('src') or ''), 'visible': f.is_displayed()}
                            for f in driver.find_elements(By.CSS_SELECTOR, 'iframe')]
        body = driver.find_element(By.TAG_NAME, 'body').text.lower()
        result['page_markers'] = [label for label, pattern in {
            'access_denied': r'access denied|zugriff verweigert|forbidden',
            'maintenance': r'wartungsarbeiten|maintenance|temporarily unavailable',
            'captcha': r'captcha|verify you are human|bestätigen sie.*mensch',
            'javascript_required': r'enable javascript|javascript aktivieren',
            'login': r'anmelden|einloggen|sign in',
        }.items() if re.search(pattern, body)]
        result['console_categories'] = sorted({category for entry in driver.get_log('browser')
            if entry.get('level') == 'SEVERE' for category in error_categories(entry.get('message', ''))})
        failures = []
        for entry in driver.get_log('performance'):
            msg = json.loads(entry['message'])['message']
            params = msg.get('params', {})
            if msg['method'] == 'Network.responseReceived':
                response = params.get('response', {})
                if response.get('status', 0) >= 400:
                    failures.append({'host': host(response.get('url', '')), 'type': params.get('type'),
                                     'status': response['status']})
            elif msg['method'] == 'Network.loadingFailed':
                error = params.get('errorText', '')
                failures.append({'type': params.get('type'),
                    'network_error': error if re.fullmatch(r'net::ERR_[A-Z_]{1,80}', error) else 'other'})
        result['resource_failures'] = failures[:20]
        result['status'] = 'complete'
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                result['cleanup_failed'] = True
        result['finished_at'] = utcnow()
    return result


def main():
    if any(os.getenv(key) for key in ('ALDI_USER', 'ALDI_PASS', 'LIDL_USER', 'LIDL_PASS')):
        raise RuntimeError('Public probe must run without provider credentials')
    report = {'scope': 'public_pages_only', 'providers': [
        probe(name, url) for name, url in [('aldi_talk', ALDI_LOGIN_URL), ('lidl_connect', LIDL_LOGIN_URL)]]}
    write_report('portal-probe-report.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
