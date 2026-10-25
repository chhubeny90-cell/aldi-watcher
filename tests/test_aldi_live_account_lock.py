from unittest.mock import Mock
import json

from core.database import Database
import aldi_live_refill as live


def _prepare(monkeypatch, tmp_path):
    driver = Mock()
    monkeypatch.setenv('GITHUB_ACTIONS', 'false')
    db_path = tmp_path / 'journal.sqlite'
    Database(str(db_path))
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(db_path))
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    monkeypatch.setenv('ALDI_EXPECTED_ACCOUNT', '01500000000')
    monkeypatch.setenv('ALDI_REQUIRED_TARGET_SUFFIX', '0000')
    monkeypatch.setattr(live, 'REPORT_PATH', str(tmp_path / 'report.json'))
    monkeypatch.setattr(live.watcher, 'ALDI_ACCOUNT_USER', '01500000000')
    monkeypatch.setattr(live.watcher, 'configure_credentials', lambda *_: True)
    monkeypatch.setattr(live.watcher, 'build_driver', lambda: driver)
    return driver


def test_login_failure_outcome_uses_only_sanitized_account_lock_flag(monkeypatch):
    driver = object()
    monkeypatch.setattr(live, 'diagnostics', lambda *_: {
        'provider_indications': {'account_locked': True, 'credential_problem': False}
    })
    assert live._login_failure_outcome(driver) == 'account_locked'


def test_login_failure_outcome_fails_closed_when_diagnostics_unavailable(monkeypatch):
    monkeypatch.setattr(live, 'diagnostics', Mock(side_effect=RuntimeError('unavailable')))
    assert live._login_failure_outcome(object()) == 'auth_failed'


def test_account_lock_after_login_exception_is_reported_without_booking(monkeypatch, tmp_path):
    driver = _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(live.watcher, 'aldi_login', Mock(side_effect=RuntimeError('login stopped')))
    monkeypatch.setattr(live, 'diagnostics', lambda *_: {
        'provider_indications': {'account_locked': True}
    })
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)

    assert live.main() == 2
    click.assert_not_called()
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['outcome'] == 'account_locked'
    assert report['booking_clicks'] == 0
    assert report['confirmation_clicks'] == 0


def test_non_lock_login_exception_preserves_generic_error_path(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path)
    monkeypatch.setattr(live.watcher, 'aldi_login', Mock(side_effect=RuntimeError('browser failure')))
    monkeypatch.setattr(live, 'diagnostics', lambda *_: {
        'provider_indications': {'account_locked': False}
    })

    assert live.main() == 2
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['outcome'] == 'error'
    assert report['exception_type'] == 'RuntimeError'
