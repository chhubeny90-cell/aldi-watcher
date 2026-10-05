"""Fail-closed, one-shot monitoring; no booking capability or raw portal logs."""
import argparse
import contextvars
import datetime as dt
import json
import math
import os
import random
import re
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

_CONTEXT = contextvars.ContextVar('monitor_context', default=None)


def phase(name):
    context = _CONTEXT.get()
    if context is not None:
        context['phase'] = name


def require_origin(driver, expected):
    actual = urlsplit(driver.current_url)
    if actual.scheme != 'https' or actual.hostname != urlsplit(expected).hostname:
        raise PermissionError('unexpected_origin')


def navigate(driver, url, attempts=2):
    """Retry only idempotent page navigation, never form submission or booking."""
    from selenium.common.exceptions import TimeoutException
    for attempt in range(attempts):
        try:
            driver.get(url)
            return
        except TimeoutException:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(8, 2 ** attempt) + random.uniform(0, .25))


def remaining_gb(text):
    """Reject total allowance/advertising and conflicting remaining-volume values."""
    values = set()
    label = r'(?:verbleibend|verfügbar|übrig|restvolumen|restliches datenvolumen)'
    quantity = r'(?<![\d.,+\-])(\d+(?:[.,]\d+)?)\s*(GB|MB)'
    for pattern in (quantity + r'\s*' + label, label + r'\s*:?\s*' + quantity):
        for number, unit in re.findall(pattern, text, re.IGNORECASE):
            value = float(number.replace(',', '.'))
            values.add(value / 1000 if unit.upper() == 'MB' else value)
    return values.pop() if len(values) == 1 else None


def session_visible(driver):
    """A URL match or a generic balance label alone is not authentication."""
    from selenium.webdriver.common.by import By
    passwords = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
    logout = driver.find_elements(By.XPATH,
        "//a[contains(@href,'logout') or contains(@href,'logoff')] | "
        "//button[contains(.,'Abmelden') or contains(.,'Logout')]")
    return (not any(e.is_displayed() for e in passwords)
            and any(e.is_displayed() for e in logout)
            and bool(driver.get_cookies()))


def evaluate_run(results, auto_book_enabled=False):
    successful = sum(r.get('login_ok') is True and r.get('status') == 'ok' for r in results)
    status = 'success' if results and successful == len(results) else ('degraded' if successful else 'failed')
    config_error = any(r.get('status') == 'config_error' for r in results)
    return dict(status=status, monitoring_status=status,
                reason=('Alle Anbieter erfolgreich geprüft' if status == 'success' else
                        'Mindestens ein Anbieter konnte nicht geprüft werden' if status == 'degraded' else
                        'Keine erfolgreiche Anbieterprüfung'),
                login_failures=sum(r.get('login_ok') is not True for r in results),
                check_failures=len(results)-successful, providers_checked=len(results),
                successful_logins=sum(r.get('login_ok') is True for r in results),
                exit_code=3 if config_error else {'success': 0, 'failed': 1, 'degraded': 2}[status],
                auto_book_enabled=auto_book_enabled,
                auto_booking={'enabled': False, 'executed': False, 'reason': 'monitoring_only'})


def diagnostics(driver):
    """Allowlisted metadata only; no bodies, URLs, headers, cookie values or tokens."""
    result = dict(http_status=None, redirect_count=None, csrf_found=None,
                  cookie_count=None, login_form_visible=None, page_host=None)
    if driver is None:
        return result
    try:
        from selenium.webdriver.common.by import By
        host = urlsplit(driver.current_url).hostname
        allowed = {'www.alditalk-kundenportal.de', 'kundenkonto.lidl-connect.de'}
        result['page_host'] = host if host in allowed else 'other'
        result['cookie_count'] = len(driver.get_cookies())
        result['login_form_visible'] = any(e.is_displayed() for e in driver.find_elements(By.CSS_SELECTOR, "input[type='password']"))
        result['csrf_found'] = bool(driver.find_elements(By.CSS_SELECTOR, "input[name*='csrf'], input[name*='CSRF'], meta[name*='csrf']"))
        redirects = 0
        for entry in driver.get_log('performance'):
            message = json.loads(entry['message'])['message']
            params = message.get('params', {})
            if params.get('type') != 'Document':
                continue
            if message['method'] == 'Network.requestWillBeSent' and 'redirectResponse' in params:
                redirects += 1
            if message['method'] == 'Network.responseReceived':
                response = params['response']
                if response.get('url') == driver.current_url:
                    result['http_status'] = int(response['status'])
        result['redirect_count'] = redirects
    except Exception:
        pass
    return result


def execute_provider(name, factory, login, read, run_id):
    from selenium.common.exceptions import TimeoutException, WebDriverException
    started = time.monotonic()
    result = dict(provider=name, run_id=run_id, phase='browser_start', login_ok=False,
                  status='error', message='Prüfung fehlgeschlagen')
    token = _CONTEXT.set(result)
    driver = None
    try:
        driver = factory()
        phase('login')
        if not login(driver):
            result.update(status='auth_failed', message='Anmeldung nicht bestätigt')
        else:
            # Login helpers and protected-page read both require session evidence.
            phase('session_validation')
            if not session_visible(driver):
                raise ValueError('session_invalid')
            result['login_ok'] = True
            phase('usage_read')
            usage = read(driver)
            remaining = usage.get('inland_frei_gb')
            if isinstance(remaining, bool) or not isinstance(remaining, (int, float)) or not math.isfinite(remaining) or remaining < 0:
                raise ValueError('usage_invalid')
            result.update(status='ok', message='Session und Restvolumen geprüft', phase='complete')
    except TimeoutException:
        result.update(status='timeout', message='Zeitlimit in protokollierter Phase erreicht')
    except WebDriverException:
        result.update(status='browser_error', message='Browser- oder Navigationsfehler')
    except PermissionError:
        result.update(login_ok=False, status='auth_failed', message='Session oder Portal-Domain nicht validiert')
    except ValueError:
        result.update(status='validation_failed', message='Session oder Nutzdaten nicht eindeutig validiert')
    except Exception:
        result.update(status='error', message='Unerwarteter interner Fehler')
    finally:
        result.update(diagnostics(driver))
        if result['status'] != 'ok':
            code = result.get('http_status')
            category = {401: 'auth_failed', 403: 'access_denied', 429: 'rate_limited'}.get(code)
            if category or (code is not None and code >= 500):
                result['status'] = category or 'portal_error'
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                result['cleanup_failed'] = True
                if result['status'] == 'ok':
                    result.update(status='browser_error', message='Browser konnte nicht beendet werden')
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        _CONTEXT.reset(token)
    return result


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_report(path, report):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.' + uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, target)


def run_cli(factory, providers, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-once', action='store_true', help='One shot (also the default)')
    parser.add_argument('--provider', choices=['all', *providers], default='all')
    parser.add_argument('--report', default='monitoring-report.json')
    args = parser.parse_args(argv)
    started = utcnow()
    monotonic_start = time.monotonic()
    run_id = started + '-' + uuid4().hex[:8]
    report = dict(run_id=run_id, started_at=started, finished_at=None, status='running',
                  scheduled=os.getenv('GITHUB_EVENT_NAME') == 'schedule',
                  commit=os.getenv('GITHUB_SHA'), providers=[])
    write_report(args.report, report)
    requested = os.getenv('AUTO_BOOK_ENABLED', 'false').lower()
    for name, (prefix, login, read) in providers.items():
        if args.provider not in ('all', name):
            continue
        if requested != 'false' or not all(os.getenv(prefix+'_'+field) for field in ('USER', 'PASS')):
            result = dict(run_id=run_id, provider=name, phase='configuration', status='config_error',
                          login_ok=False, elapsed_seconds=0,
                          message='Zugangsdaten fehlen oder Monitoring-Modus nicht explizit sicher')
        else:
            result = execute_provider(name, factory, login, read, run_id)
        report['providers'].append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    report.update(evaluate_run(report['providers'], requested == 'true'))
    report['finished_at'] = utcnow()
    report['elapsed_seconds'] = round(time.monotonic() - monotonic_start, 3)
    write_report(args.report, report)
    print(json.dumps({k:v for k,v in report.items() if k != 'providers'}, ensure_ascii=False), flush=True)
    summary_path = os.getenv('GITHUB_STEP_SUMMARY')
    if summary_path:
        with open(summary_path, 'a') as summary:
            summary.write(f"## Monitoring: {report['status']}\n\nRun-ID: `{run_id}`\n\nAuto-Buchung: deaktiviert\n\n")
            for item in report['providers']:
                summary.write(f"- {item['provider']}: **{item['status']}** ({item['phase']})\n")
    if report['exit_code']:
        print('::error::Monitoring fehlgeschlagen oder unvollständig; siehe sichere Laufzusammenfassung.')
    return report['exit_code']
