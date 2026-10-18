import json

from core.database import Database
import github_live_refill as hosted


def test_begin_recharge_sync_sees_pending_before_return(tmp_path, monkeypatch):
    path = tmp_path / 'journal.db'
    db = Database(str(path))
    observed = []

    def capture_sync(journal_path):
        records = Database(str(journal_path)).get_unresolved_recharges()
        observed.append([(record.recharge_id, record.status) for record in records])

    monkeypatch.setattr(hosted, 'sync_journal', capture_sync)
    recharge_id = hosted._syncing_begin(db, 'alditalk', '01500000000')

    assert observed == [[(recharge_id, 'PENDING')]]


def test_status_transition_is_synchronized(tmp_path, monkeypatch):
    path = tmp_path / 'journal.db'
    db = Database(str(path))
    recharge_id = hosted._ORIGINAL_BEGIN(db, 'alditalk', '01500000000')
    observed = []

    def capture_sync(journal_path):
        with Database(str(journal_path))._connect() as conn:
            observed.append(conn.execute(
                'SELECT status FROM recharges WHERE recharge_id = ?', (recharge_id,)
            ).fetchone()[0])

    monkeypatch.setattr(hosted, 'sync_journal', capture_sync)
    result = hosted._syncing_set(db, recharge_id, 'SUCCESS')

    assert result == 'SUCCESS'
    assert observed == ['SUCCESS']


def _hosted_env(monkeypatch, tmp_path):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('ALDI_REMOTE_JOURNAL', 'true')
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str((tmp_path / 'journal.db').resolve()))
    monkeypatch.setattr(hosted, '_journal_path', lambda: (tmp_path / 'journal.db').resolve())


def test_active_auth_backoff_skips_live_runner_before_credentials(tmp_path, monkeypatch):
    _hosted_env(monkeypatch, tmp_path)
    report = tmp_path / 'report.json'
    monkeypatch.setenv('ALDI_LIVE_REPORT', str(report))
    monkeypatch.setattr(hosted, 'auth_backoff_active', lambda: True)
    called = []
    monkeypatch.setattr(hosted.live, 'main', lambda: called.append(True))

    assert hosted.main() == 0
    assert called == []
    payload = json.loads(report.read_text())
    assert payload['outcome'] == 'auth_backoff_active'
    assert payload['booking_clicks'] == 0


def test_account_lock_sets_24_hour_backoff(tmp_path, monkeypatch):
    _hosted_env(monkeypatch, tmp_path)
    monkeypatch.setattr(hosted, 'auth_backoff_active', lambda: False)
    monkeypatch.setattr(hosted.live, 'main', lambda: 2)
    monkeypatch.setattr(hosted, '_report_outcome', lambda: 'account_locked')
    delays = []
    monkeypatch.setattr(hosted, 'set_auth_backoff', lambda hours: delays.append(hours))

    assert hosted.main() == 2
    assert delays == [24]


def test_generic_auth_failure_sets_short_backoff(tmp_path, monkeypatch):
    _hosted_env(monkeypatch, tmp_path)
    monkeypatch.setattr(hosted, 'auth_backoff_active', lambda: False)
    monkeypatch.setattr(hosted.live, 'main', lambda: 2)
    monkeypatch.setattr(hosted, '_report_outcome', lambda: 'auth_failed')
    delays = []
    monkeypatch.setattr(hosted, 'set_auth_backoff', lambda hours: delays.append(hours))

    assert hosted.main() == 2
    assert delays == [1]


def test_preclaimed_mail_cannot_bypass_unverified_handoff(monkeypatch):
    import pytest
    monkeypatch.setenv("ALDI_TRIGGER_PRECLAIMED", "true")
    monkeypatch.setenv("ALDI_TRIGGER_MESSAGE_KEY", "synthetic-unit-test")
    with pytest.raises(RuntimeError, match="unverified_mail_handoff_blocked"):
        hosted._claim_mail_trigger()


def test_unverified_raw_mail_trigger_cannot_start_actor(monkeypatch):
    import pytest
    monkeypatch.setenv("ALDI_TRIGGER_MESSAGE_KEY", "synthetic-mail-event")
    monkeypatch.delenv("ALDI_TRIGGER_PRECLAIMED", raising=False)
    with pytest.raises(RuntimeError, match="unverified_mail_handoff_blocked"):
        hosted._claim_mail_trigger()


def test_preclaimed_without_message_key_is_also_blocked(monkeypatch):
    import pytest
    monkeypatch.delenv("ALDI_TRIGGER_MESSAGE_KEY", raising=False)
    monkeypatch.setenv("ALDI_TRIGGER_PRECLAIMED", "true")
    with pytest.raises(RuntimeError, match="unverified_mail_handoff_blocked"):
        hosted._claim_mail_trigger()


def test_live_actor_requires_explicit_target_account(monkeypatch):
    monkeypatch.setenv("AUTO_BOOK_ENABLED", "true")
    monkeypatch.delenv("ALDI_EXPECTED_ACCOUNT", raising=False)
    monkeypatch.setattr(hosted.watcher, "configure_credentials",
                        lambda *_: (_ for _ in ()).throw(
                            AssertionError("must fail before reading credentials")
                        ))
    assert hosted._target_guard() == "target_account_guard_missing"


def test_non_live_actor_does_not_require_target_account(monkeypatch):
    monkeypatch.setenv("AUTO_BOOK_ENABLED", "false")
    monkeypatch.delenv("ALDI_EXPECTED_ACCOUNT", raising=False)
    assert hosted._target_guard() is None
