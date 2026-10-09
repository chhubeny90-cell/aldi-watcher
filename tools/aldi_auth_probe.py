"""Sanitized ALDI authentication/evidence probe.

No booking action is available here. The report contains only allowlisted
booleans, counts and coarse classifications; never field values, page text,
URLs, cookies, tokens, headers or raw exception messages.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from selenium.common.exceptions import TimeoutException, WebDriverException

import watcher
from browser_dom import element_label, find_visible_elements
from monitoring import safe_refill_evidence, utcnow, write_report

REPORT = Path('monitoring-report.json')
_ALLOWED_WEBDRIVER_ERRORS = {
    'ElementClickInterceptedException', 'ElementNotInteractableException',
    'StaleElementReferenceException', 'JavascriptException',
    'InvalidElementStateException', 'NoSuchElementException',
    'TimeoutException', 'WebDriverException',
}


def _visible(elements):
    visible = []
    for element in elements:
        try:
            if element.is_displayed():
                visible.append(element)
        except Exception:
            pass
    return visible


def _url_class(driver):
    try:
        parsed = urlsplit(driver.current_url)
        if parsed.hostname == 'login.alditalk-kundenbetreuung.de':
            host = 'aldi_sso'
        elif parsed.hostname == 'www.alditalk-kundenportal.de':
            host = 'aldi_portal'
        else:
            host = 'other'
        path = (parsed.path or '/').casefold()
        if path.startswith('/signin/xui'):
            route = 'signin_ui'
        elif 'authorize' in path or 'oauth' in path:
            route = 'authorization_flow'
        elif 'callback' in path or 'redirect' in path:
            route = 'callback_like'
        elif path in {'', '/'}:
            route = 'root'
        else:
            route = 'other'
        return host, route
    except Exception:
        return 'unknown', 'unknown'


def _field_state(driver, element, prefix):
    state = {
        f'{prefix}_field_present': element is not None,
        f'{prefix}_has_value': None,
        f'{prefix}_aria_invalid': None,
        f'{prefix}_disabled': None,
        f'{prefix}_readonly': None,
        f'{prefix}_form_associated': None,
        f'{prefix}_native_valid': None,
        f'{prefix}_value_missing': None,
        f'{prefix}_pattern_mismatch': None,
        f'{prefix}_type_mismatch': None,
        f'{prefix}_too_short': None,
        f'{prefix}_too_long': None,
        f'{prefix}_custom_error': None,
    }
    if element is None:
        return state
    try:
        state[f'{prefix}_has_value'] = bool(
            driver.execute_script('return Boolean(arguments[0].value);', element)
        )
        state[f'{prefix}_form_associated'] = bool(
            driver.execute_script('return arguments[0].form !== null;', element)
        )
    except Exception:
        pass
    try:
        state[f'{prefix}_aria_invalid'] = (
            (element.get_attribute('aria-invalid') or '').lower() == 'true'
        )
        state[f'{prefix}_disabled'] = bool(element.get_attribute('disabled'))
        state[f'{prefix}_readonly'] = bool(element.get_attribute('readonly'))
    except Exception:
        pass
    try:
        validity = driver.execute_script(
            """
            const v = arguments[0].validity;
            if (!v) return null;
            return {valid:!!v.valid,valueMissing:!!v.valueMissing,
                    patternMismatch:!!v.patternMismatch,typeMismatch:!!v.typeMismatch,
                    tooShort:!!v.tooShort,tooLong:!!v.tooLong,customError:!!v.customError};
            """, element)
        if isinstance(validity, dict):
            mapping = {
                'valid': 'native_valid', 'valueMissing': 'value_missing',
                'patternMismatch': 'pattern_mismatch', 'typeMismatch': 'type_mismatch',
                'tooShort': 'too_short', 'tooLong': 'too_long',
                'customError': 'custom_error',
            }
            for source, target in mapping.items():
                state[f'{prefix}_{target}'] = bool(validity.get(source))
    except Exception:
        pass
    return state


def _network_state(driver):
    state = {
        'network_request_count': 0, 'network_post_count': 0,
        'network_document_count': 0, 'network_fetch_xhr_count': 0,
        'network_401_count': 0, 'network_401_document_count': 0,
        'network_401_fetch_xhr_count': 0, 'network_401_get_count': 0,
        'network_401_post_count': 0, 'network_401_sso_count': 0,
        'network_401_portal_count': 0, 'network_401_other_count': 0,
        'network_403_count': 0, 'network_404_count': 0,
        'network_429_count': 0, 'network_5xx_count': 0,
        'network_failed_count': 0, 'redirect_count': 0,
    }
    methods = {}
    try:
        for entry in driver.get_log('performance'):
            message = json.loads(entry['message'])['message']
            params = message.get('params', {})
            event = message.get('method')
            request_id = params.get('requestId')
            if event == 'Network.requestWillBeSent':
                request = params.get('request', {})
                method = str(request.get('method', '')).upper()
                resource_type = str(params.get('type', ''))
                state['network_request_count'] += 1
                if method == 'POST':
                    state['network_post_count'] += 1
                if resource_type == 'Document':
                    state['network_document_count'] += 1
                elif resource_type in {'Fetch', 'XHR'}:
                    state['network_fetch_xhr_count'] += 1
                if request_id:
                    methods[request_id] = method
                if 'redirectResponse' in params:
                    state['redirect_count'] += 1
                continue
            if event == 'Network.loadingFailed':
                state['network_failed_count'] += 1
                continue
            if event != 'Network.responseReceived':
                continue
            response = params.get('response', {})
            status = int(response.get('status', 0) or 0)
            if status == 401:
                state['network_401_count'] += 1
                resource_type = str(params.get('type', ''))
                if resource_type == 'Document':
                    state['network_401_document_count'] += 1
                elif resource_type in {'Fetch', 'XHR'}:
                    state['network_401_fetch_xhr_count'] += 1
                method = methods.get(request_id, '')
                if method == 'GET':
                    state['network_401_get_count'] += 1
                elif method == 'POST':
                    state['network_401_post_count'] += 1
                try:
                    host = urlsplit(response.get('url', '')).hostname
                except Exception:
                    host = None
                if host == 'login.alditalk-kundenbetreuung.de':
                    state['network_401_sso_count'] += 1
                elif host == 'www.alditalk-kundenportal.de':
                    state['network_401_portal_count'] += 1
                else:
                    state['network_401_other_count'] += 1
            elif status == 403:
                state['network_403_count'] += 1
            elif status == 404:
                state['network_404_count'] += 1
            elif status == 429:
                state['network_429_count'] += 1
            elif 500 <= status <= 599:
                state['network_5xx_count'] += 1
    except Exception:
        pass
    return state


def _structural_state(driver):
    host, route = _url_class(driver)
    state = {
        'host_class': host, 'path_class': route, 'cookie_count': None,
        'visible_input_count': None, 'visible_password_count': None,
        'username_candidate_count': None, 'username_input_type': None,
        'password_input_type': None, 'mfa_input_visible': False,
        'alert_region_visible': False, 'invalid_input_count': None,
        'visible_control_count': None, 'login_submit_visible': False,
        'login_submit_enabled': False, 'login_submit_type': None,
        'continue_control_visible': False, 'consent_control_visible': False,
        'logout_visible': False, 'frame_count': None, 'document_ready': None,
    }
    username = password = None
    try:
        state['cookie_count'] = len(driver.get_cookies())
        inputs = _visible(find_visible_elements(driver, 'input'))
        state['visible_input_count'] = len(inputs)
        passwords = [e for e in inputs if (e.get_attribute('type') or '').lower() == 'password']
        usernames = [e for e in inputs if
                     (e.get_attribute('autocomplete') or '').lower() == 'username'
                     or (e.get_attribute('type') or '').lower() in {'tel', 'email'}]
        if not usernames:
            usernames = [e for e in inputs if (e.get_attribute('type') or '').lower() == 'text']
        state['visible_password_count'] = len(passwords)
        state['username_candidate_count'] = len(usernames)
        password = passwords[0] if len(passwords) == 1 else None
        username = usernames[0] if len(usernames) == 1 else None
        state['username_input_type'] = ((username.get_attribute('type') or 'text').lower()
                                        if username is not None else None)
        state['password_input_type'] = ((password.get_attribute('type') or '').lower()
                                        if password is not None else None)
        state['mfa_input_visible'] = any(
            (e.get_attribute('autocomplete') or '').lower() == 'one-time-code' for e in inputs)
        state['invalid_input_count'] = sum(
            (e.get_attribute('aria-invalid') or '').lower() == 'true' for e in inputs)
    except Exception:
        pass
    state.update(_field_state(driver, username, 'username'))
    state.update(_field_state(driver, password, 'password'))
    try:
        state['alert_region_visible'] = bool(_visible(find_visible_elements(
            driver, "[role='alert'],[aria-live='assertive'],[aria-live='polite']")))
        controls = _visible(find_visible_elements(
            driver, "button,a,[role='button'],input[type='submit']"))
        state['visible_control_count'] = len(controls)
        labels = [element_label(driver, e).strip().casefold() for e in controls]
        submits = [e for e, label in zip(controls, labels) if label == 'anmelden']
        state['login_submit_visible'] = len(submits) == 1
        if len(submits) == 1:
            submit = submits[0]
            state['login_submit_enabled'] = bool(
                submit.is_enabled() and submit.get_attribute('aria-disabled') != 'true')
            submit_type = (submit.get_attribute('type') or '').lower()
            state['login_submit_type'] = submit_type if submit_type in {'submit', 'button'} else 'other'
        state['continue_control_visible'] = any(
            label in {'weiter', 'fortfahren', 'weiter zu aldi talk', 'zum kundenkonto'}
            for label in labels)
        state['consent_control_visible'] = any(
            label in {'zulassen', 'bestätigen', 'zustimmen', 'einverstanden'}
            for label in labels)
        state['logout_visible'] = any(label in {'abmelden', 'logout'} for label in labels)
        state['frame_count'] = len(driver.find_elements('css selector', 'iframe'))
        ready = driver.execute_script('return document.readyState')
        state['document_ready'] = ready if ready in {'loading', 'interactive', 'complete'} else 'unknown'
    except Exception:
        pass
    state.update(_network_state(driver))
    return state


def _snapshot(report, driver):
    diagnostic = getattr(watcher, 'ALDI_AUTH_DIAGNOSTIC_STATE', {})
    if isinstance(diagnostic, dict):
        report.update({key: value for key, value in diagnostic.items()
                       if isinstance(value, (bool, type(None)))})
    report.update(_structural_state(driver))


def _webdriver_error_class(exc):
    name = type(exc).__name__
    return name if name in _ALLOWED_WEBDRIVER_ERRORS else 'WebDriverException'


def main():
    report = {
        'started_at': utcnow(), 'provider': 'aldi_talk',
        'mode': 'read_only_auth_probe',
        'auto_booking': {'enabled': False, 'executed': False},
        'login_ok': False, 'status': 'error',
    }
    driver = None
    try:
        if not watcher.configure_credentials('ALDI'):
            report.update(status='config_error', reason='credentials_missing')
            return 3
        driver = watcher.build_driver()
        try:
            login_ok = watcher.aldi_login(driver)
        except TimeoutException:
            report.update(status='auth_timeout', reason='session_validation_timeout')
            _snapshot(report, driver)
            return 1
        except WebDriverException as exc:
            report.update(status='browser_error', reason='webdriver_error',
                          webdriver_error_class=_webdriver_error_class(exc))
            _snapshot(report, driver)
            return 1
        if not login_ok:
            report.update(status='auth_failed', reason='login_not_confirmed')
            _snapshot(report, driver)
            return 1
        report['login_ok'] = True
        _snapshot(report, driver)
        usage = watcher.aldi_read_status(driver)
        report.update(safe_refill_evidence('aldi_talk', usage))
        report.update(status='ok', reason='authenticated_read_only_probe_complete')
        return 0
    except PermissionError:
        report.update(status='auth_failed', reason='unexpected_origin_or_session')
        if driver is not None:
            _snapshot(report, driver)
        return 1
    except ValueError:
        report.update(status='validation_failed', reason='protected_data_not_unambiguous')
        if driver is not None:
            _snapshot(report, driver)
        return 1
    except Exception:
        report.update(status='error', reason='internal_error')
        if driver is not None:
            _snapshot(report, driver)
        return 1
    finally:
        report['finished_at'] = utcnow()
        write_report(REPORT, report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == '__main__':
    raise SystemExit(main())
