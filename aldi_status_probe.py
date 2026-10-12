"""Read-only ALDI live probe: authenticate, verify account, read usage, never book."""

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from selenium.common.exceptions import TimeoutException
from monitoring import _CONTEXT

import watcher
from core.aldi_http_login import phone_identifier
from core.aldi_refill import verify_account_selenium


REPORT_PATH = os.environ.get('ALDI_STATUS_REPORT', 'aldi-status-probe.json')


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _write(report):
    path = Path(REPORT_PATH)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def _phase(report, value):
    report['phase'] = value
    _write(report)


def _valid_remaining(value):
    return (not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value >= 0)


def main():
    report = {
        'started_at': utcnow(),
        'finished_at': None,
        'phase': 'startup',
        'outcome': 'unknown',
        'read_only': True,
        'login_success': False,
        'account_verified': False,
        'status_success': False,
        'booking_clicks': 0,
    }
    driver = None

    try:
        _phase(report, 'credentials')
        if not watcher.configure_credentials('ALDI'):
            report['outcome'] = 'credentials_unavailable'
            return 3

        account = phone_identifier(watcher.ALDI_ACCOUNT_USER)
        driver = watcher.build_driver()

        _phase(report, 'login')
        phase_context = {'phase': 'login_page'}
        token = _CONTEXT.set(phase_context)
        try:
            try:
                logged_in = watcher.aldi_login(driver)
            except TimeoutException:
                stage = phase_context['phase']
                report['failed_phase'] = stage
                report['outcome'] = (stage + '_timeout') if stage in {
                    'login_page', 'username_field', 'password_field',
                    'session_validation', 'protected_page_probe'
                } else 'login_timeout'
                return 2
        finally:
            _CONTEXT.reset(token)
        if not logged_in:
            report['outcome'] = 'auth_failed'
            return 2
        report['login_success'] = True
        _write(report)

        _phase(report, 'account_verify')
        try:
            verify_account_selenium(driver, account)
        except Exception:
            report['outcome'] = 'account_verify_failed'
            return 2
        report['account_verified'] = True
        _write(report)

        _phase(report, 'status')
        try:
            status = watcher.aldi_read_status(driver, include_refill=False)
        except TimeoutException:
            report['outcome'] = 'status_read_timeout'
            return 2

        remaining = status.get('inland_frei_gb')
        if not _valid_remaining(remaining):
            report['outcome'] = 'status_read_failed'
            return 2

        report['status_success'] = True
        report['remaining_gb'] = round(float(remaining), 3)
        report['outcome'] = 'not_needed' if remaining >= 1.0 else 'below_one_gb'
        _phase(report, 'complete')
        return 0
    except Exception as exc:
        report['outcome'] = 'error'
        report['exception_type'] = type(exc).__name__
        return 2
    finally:
        report['finished_at'] = utcnow()
        _write(report)
        print(json.dumps({
            'outcome': report['outcome'],
            'phase': report['phase'],
            'login_success': report['login_success'],
            'account_verified': report['account_verified'],
            'status_success': report['status_success'],
            'booking_clicks': 0,
        }), flush=True)
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
