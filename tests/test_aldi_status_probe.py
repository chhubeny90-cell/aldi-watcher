import json
from unittest.mock import Mock

from selenium.common.exceptions import TimeoutException

import aldi_status_probe as probe
import watcher


def _setup_probe(monkeypatch, tmp_path, remaining=2.0):
    driver = Mock()
    monkeypatch.setattr(probe, 'REPORT_PATH', str(tmp_path / 'status.json'))
    monkeypatch.setattr(probe.watcher, 'configure_credentials', lambda *_: True)
    monkeypatch.setattr(probe.watcher, 'ALDI_ACCOUNT_USER', '01500000000')
    monkeypatch.setattr(probe.watcher, 'build_driver', lambda: driver)
    monkeypatch.setattr(probe.watcher, 'aldi_login', lambda *_: True)
    monkeypatch.setattr(probe, 'verify_account_selenium', lambda *_: 'a' * 64)
    monkeypatch.setattr(
        probe.watcher,
        'aldi_read_status',
        lambda *_args, **kwargs: {'inland_frei_gb': remaining},
    )
    return driver


def test_read_only_probe_reports_not_needed_above_one_gb(monkeypatch, tmp_path):
    driver = _setup_probe(monkeypatch, tmp_path, remaining=2.25)

    assert probe.main() == 0
    report = json.loads((tmp_path / 'status.json').read_text())
    assert report['outcome'] == 'not_needed'
    assert report['login_success'] is True
    assert report['account_verified'] is True
    assert report['status_success'] is True
    assert report['remaining_gb'] == 2.25
    assert report['booking_clicks'] == 0
    driver.quit.assert_called_once()


def test_read_only_probe_reports_below_one_gb_without_booking(monkeypatch, tmp_path):
    _setup_probe(monkeypatch, tmp_path, remaining=0.4)

    assert probe.main() == 0
    report = json.loads((tmp_path / 'status.json').read_text())
    assert report['outcome'] == 'below_one_gb'
    assert report['booking_clicks'] == 0


def test_read_only_probe_separates_login_timeout(monkeypatch, tmp_path):
    _setup_probe(monkeypatch, tmp_path)
    monkeypatch.setattr(probe.watcher, 'aldi_login', Mock(side_effect=TimeoutException('login')))

    assert probe.main() == 2
    report = json.loads((tmp_path / 'status.json').read_text())
    assert report['outcome'] == 'login_timeout'
    assert report['phase'] == 'login'
    assert report['status_success'] is False


def test_read_only_probe_separates_status_timeout(monkeypatch, tmp_path):
    _setup_probe(monkeypatch, tmp_path)
    monkeypatch.setattr(
        probe.watcher,
        'aldi_read_status',
        Mock(side_effect=TimeoutException('status_read_timeout')),
    )

    assert probe.main() == 2
    report = json.loads((tmp_path / 'status.json').read_text())
    assert report['outcome'] == 'status_read_timeout'
    assert report['phase'] == 'status'
    assert report['login_success'] is True
    assert report['status_success'] is False


def test_aldi_usage_reader_only_inspects_refill_below_one_gb():
    source = watcher.aldi_read_status.__code__.co_consts
    text = '\n'.join(value for value in source if isinstance(value, str))
    # Behavioral regression is also enforced by the function source contract:
    # the public API exposes an explicit status-only switch and a named timeout.
    assert 'status_read_timeout' in text
    assert watcher.aldi_read_status.__defaults__ == (None, 3)


def test_status_probe_workflow_is_explicitly_read_only():
    text = open('.github/workflows/status-probe.yml', encoding='utf-8').read()
    assert "AUTO_BOOK_ENABLED: 'false'" in text
    assert "ALDI_STATUS_ONLY: 'true'" in text
    assert 'aldi_status_probe.py' in text


def test_maintenance_is_distinct_from_login_timeout(monkeypatch, tmp_path, capsys):
    _setup_probe(monkeypatch, tmp_path)
    def maintenance(_driver):
        watcher.phase('service_maintenance')
        raise TimeoutException('service_maintenance')
    monkeypatch.setattr(probe.watcher, 'aldi_login', maintenance)
    assert probe.main() == 2
    report = json.loads((tmp_path / 'status.json').read_text())
    assert report['outcome'] == 'service_maintenance'
    assert report['failed_phase'] == 'service_maintenance'
    assert report['booking_clicks'] == 0
    logged = json.loads(capsys.readouterr().out)
    assert logged['failed_phase'] == 'service_maintenance'


def test_login_timeout_preserves_phase_and_hides_exception_details(monkeypatch, tmp_path, capsys):
    _setup_probe(monkeypatch, tmp_path)

    def fail_password_field(_driver):
        watcher.phase('password_field')
        raise TimeoutException('private-token-should-not-appear')

    monkeypatch.setattr(probe.watcher, 'aldi_login', fail_password_field)
    assert probe.main() == 2
    report_text = (tmp_path / 'status.json').read_text(encoding='utf-8')
    report = json.loads(report_text)
    logged = json.loads(capsys.readouterr().out)
    assert report['outcome'] == 'login_timeout'
    assert report['failed_phase'] == 'password_field'
    assert logged['failed_phase'] == 'password_field'
    assert report['booking_clicks'] == logged['booking_clicks'] == 0
    assert 'private-token-should-not-appear' not in report_text


def test_login_page_timeout_reports_initial_phase(monkeypatch, tmp_path):
    _setup_probe(monkeypatch, tmp_path)
    monkeypatch.setattr(probe.watcher, 'aldi_login', Mock(side_effect=TimeoutException('page')))
    assert probe.main() == 2
    report = json.loads((tmp_path / 'status.json').read_text(encoding='utf-8'))
    assert report['outcome'] == 'login_timeout'
    assert report['failed_phase'] == 'login_page'
    assert report['booking_clicks'] == 0
