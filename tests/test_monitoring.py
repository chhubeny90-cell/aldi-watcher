import json
import subprocess
import sys
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import TimeoutException, WebDriverException
import monitoring as m
import watcher


@pytest.mark.parametrize('results,status,exit_code', [
    ([], 'failed', 1),
    ([{'login_ok': False, 'status': 'timeout'}]*2, 'failed', 1),
    ([{'login_ok': True, 'status': 'ok'}, {'login_ok': False, 'status': 'timeout'}], 'degraded', 2),
    ([{'login_ok': True, 'status': 'ok'}]*2, 'success', 0),
    ([{'login_ok': True, 'status': 'unknown_new_status'}], 'failed', 1),
    ([{'login_ok': False, 'status': 'circuit_open'}], 'failed', 1),
    ([{'login_ok': False, 'status': 'config_error'}], 'failed', 3),
    ([{'login_ok': True, 'status': 'ok'}, {'login_ok': True, 'status': 'validation_failed'}], 'degraded', 2),
])
def test_status_contract(results, status, exit_code):
    summary = m.evaluate_run(results)
    assert summary['status'] == status
    assert summary['exit_code'] == exit_code
    assert not summary['auto_booking']['executed']


def driver():
    obj = Mock()
    obj.current_url = watcher.LIDL_LOGIN_URL
    obj.get_cookies.return_value = [{'name': 'session', 'value': 'PRIVATE_COOKIE'}]
    obj.get_log.return_value = []
    obj.find_elements.return_value = []
    return obj


def test_lidl_login_url_alone_is_not_success():
    assert not m.session_visible(driver())


def test_visible_password_overrides_logout():
    obj = driver()
    obj.find_elements.return_value = [Mock(is_displayed=lambda: True)]
    assert not m.session_visible(obj)


def test_session_requires_cookie_and_logout():
    obj = driver()
    obj.find_elements.side_effect = lambda by, query: [] if 'password' in query else [Mock(is_displayed=lambda: True)]
    assert m.session_visible(obj)
    obj.get_cookies.return_value = []
    assert not m.session_visible(obj)


def test_timeout_phase_cleanup_and_redaction():
    obj = driver()
    def login(_):
        m.phase('username_field')
        raise TimeoutException('PASSWORD PRIVATE_COOKIE +49123456789')
    result = m.execute_provider('aldi_talk', lambda: obj, login, Mock(), 'test')
    assert result['status'] == 'timeout'
    assert result['phase'] == 'username_field'
    obj.quit.assert_called_once()
    assert 'PRIVATE' not in json.dumps(result)
    assert 'PASSWORD' not in json.dumps(result)
    assert '+491234' not in json.dumps(result)


def test_browser_start_failure():
    result = m.execute_provider('aldi_talk', Mock(side_effect=WebDriverException('secret')), Mock(), Mock(), 'test')
    assert result['status'] == 'browser_error'
    assert result['phase'] == 'browser_start'


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), -1, '3', True])
def test_invalid_usage_fails(monkeypatch, value):
    monkeypatch.setattr(m, 'session_visible', lambda _: True)
    result = m.execute_provider('lidl_connect', driver, lambda _: True,
                                lambda _: {'inland_frei_gb': value}, 'test')
    assert result['status'] == 'validation_failed'
    assert result['login_ok'] is True


def test_provider_isolation_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'session_visible', lambda _: True)
    for prefix in ('ALDI', 'LIDL'):
        monkeypatch.setenv(prefix+'_USER', 'fake')
        monkeypatch.setenv(prefix+'_PASS', 'fake')
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'false')
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    path = tmp_path/'report.json'
    read = Mock(return_value={'inland_frei_gb': 0})
    providers = {'aldi_talk': ('ALDI', Mock(side_effect=TimeoutException()), read),
                 'lidl_connect': ('LIDL', lambda _: True, read)}
    assert m.run_cli(driver, providers, ['--run-once', '--report', str(path)]) == 2
    data = json.loads(path.read_text())
    assert len(data['providers']) == 2
    assert data['finished_at']
    assert data['run_id'] == data['providers'][0]['run_id']
    assert not data['auto_booking']['executed']
    read.assert_called_once()
    assert path.stat().st_mode & 0o777 == 0o600


def test_real_process_exit_one_for_two_timeouts(tmp_path):
    script = '''
from unittest.mock import Mock
from selenium.common.exceptions import TimeoutException
import monitoring as m
m.diagnostics = lambda driver: {}
providers = {name: (prefix, Mock(side_effect=TimeoutException()), Mock())
             for name, prefix in [('aldi_talk', 'ALDI'), ('lidl_connect', 'LIDL')]}
raise SystemExit(m.run_cli(Mock, providers, ['--report', 'REPORT']))
'''.replace('REPORT', str(tmp_path/'report.json'))
    import os
    env = dict(os.environ, AUTO_BOOK_ENABLED='false', ALDI_USER='fake', ALDI_PASS='fake', LIDL_USER='fake', LIDL_PASS='fake')
    env.pop('GITHUB_STEP_SUMMARY', None)
    process = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True)
    assert process.returncode == 1, process.stderr
    data = json.loads((tmp_path/'report.json').read_text())
    assert data['login_failures'] == data['check_failures'] == 2


@pytest.mark.parametrize('flag', ['true', 'typo'])
def test_booking_flag_fails_before_browser(tmp_path, monkeypatch, flag):
    monkeypatch.setenv('AUTO_BOOK_ENABLED', flag)
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    factory = Mock()
    assert m.run_cli(factory, {'aldi_talk': ('ALDI', Mock(), Mock())}, ['--report', str(tmp_path/'report')]) == 3
    factory.assert_not_called()


def test_entrypoint_has_no_booking_functions():
    assert not hasattr(watcher, 'aldi_book_free_gb')
    assert not hasattr(watcher, 'lidl_book_free_option')


@pytest.mark.parametrize('text,expected', [
    ('10 GB Tarif, 500 MB verbleibend', .5),
    ('Verfügbar: 1,5 GB', 1.5),
    ('Restvolumen: 0 MB', 0),
    ('Tarif enthält 10 GB', None),
    ('1 GB verbleibend und 2 GB verfügbar', None),
])
def test_remaining_requires_unambiguous_label(text, expected):
    assert m.remaining_gb(text) == expected


def test_navigation_retries_only_bounded_get(monkeypatch):
    monkeypatch.setattr(m.time, 'sleep', lambda _: None)
    obj = Mock()
    obj.get.side_effect = [TimeoutException(), None]
    m.navigate(obj, 'https://example.invalid')
    assert obj.get.call_count == 2
    obj.get.side_effect = TimeoutException()
    with pytest.raises(TimeoutException):
        m.navigate(obj, 'https://example.invalid')
    assert obj.get.call_count == 4


def test_unexpected_origin_rejected():
    obj = driver()
    with pytest.raises(PermissionError):
        m.require_origin(obj, watcher.ALDI_LOGIN_URL)


def test_http_status_classified(monkeypatch):
    monkeypatch.setattr(m, 'diagnostics', lambda _: {'http_status': 429})
    result = m.execute_provider('aldi_talk', driver, Mock(side_effect=TimeoutException()), Mock(), 'test')
    assert result['status'] == 'rate_limited'
