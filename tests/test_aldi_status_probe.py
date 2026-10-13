import json

import aldi_status_probe as probe
import watcher
from selenium.common.exceptions import TimeoutException


def _setup_probe(monkeypatch, tmp_path):
    monkeypatch.setenv('ALDI_STATUS_REPORT', str(tmp_path / 'status.json'))
    monkeypatch.setattr(probe, 'REPORT_PATH', str(tmp_path / 'status.json'))
    monkeypatch.setattr(probe.watcher, 'configure_credentials', lambda *_: True)
    monkeypatch.setattr(probe.watcher, 'build_driver', lambda: _Driver())


class _Driver:
    def quit(self):
        return None


def test_probe_never_books_when_login_fails(monkeypatch, tmp_path):
    _setup_probe(monkeypatch, tmp_path)
    monkeypatch.setattr(probe.watcher, 'aldi_login', lambda *_: False)
    assert probe.main() == 2
    report = json.loads((tmp_path / 'status.json').read_text())
    assert report['booking_clicks'] == 0
    assert report['login_success'] is False


def test_probe_reads_status_without_refill_inspection(monkeypatch, tmp_path):
    _setup_probe(monkeypatch, tmp_path)
    monkeypatch.setattr(probe.watcher, 'aldi_login', lambda *_: True)
    called = []

    def read_status(_driver, include_refill=None, attempts=3):
        called.append((include_refill, attempts))
        return {'guthaben': '', 'inland_frei_gb': 2.0}

    monkeypatch.setattr(probe.watcher, 'aldi_read_status', read_status)
    assert probe.main() == 0
    assert called == [(False, 3)]
    report = json.loads((tmp_path / 'status.json').read_text())
    assert report['booking_clicks'] == 0
    assert report['status_success'] is True


def test_probe_reports_status_timeout_after_login(monkeypatch, tmp_path):
    _setup_probe(monkeypatch, tmp_path)
    monkeypatch.setattr(probe.watcher, 'aldi_login', lambda *_: True)

    def timeout_status(*_args, **_kwargs):
        raise TimeoutException('status_read_timeout')

    monkeypatch.setattr(probe.watcher, 'aldi_read_status', timeout_status)
    assert probe.main() == 2
    report = json.loads((tmp_path / 'status.json').read_text())
    assert report['outcome'] == 'status_read_timeout'
    assert report['phase'] == 'status'
    assert report['login_success'] is True
    assert report['status_success'] is False


def test_aldi_usage_reader_only_inspects_refill_below_one_gb():
    source = watcher.aldi_read_status.__code__.co_consts
    text = '\n'.join(value for value in source if isinstance(value, str))
    assert 'status_read_timeout' in text
    assert watcher.aldi_read_status.__defaults__ == (None, 3)


def test_authenticated_status_probe_workflow_is_disabled():
    text = open('.github/workflows/status-probe.yml', encoding='utf-8').read()
    assert 'ALDI Read-Only Status Probe (disabled)' in text
    assert 'Authenticated ALDI status probing is disabled.' in text
    assert 'aldi_status_probe.py' not in text
    assert 'ALDI_PASS' not in text
    assert 'ALDI_USER' not in text


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
