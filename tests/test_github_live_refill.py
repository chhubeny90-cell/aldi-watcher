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


def test_account_lock_sets_six_hour_backoff(tmp_path, monkeypatch):
    _hosted_env(monkeypatch, tmp_path)
    monkeypatch.setattr(hosted, 'auth_backoff_active', lambda: False)
    monkeypatch.setattr(hosted.live, 'main', lambda: 2)
    monkeypatch.setattr(hosted, '_report_outcome', lambda: 'account_locked')
    delays = []
    monkeypatch.setattr(hosted, 'set_auth_backoff', lambda hours: delays.append(hours))

    assert hosted.main() == 2
    assert delays == [6]


def test_generic_auth_failure_sets_short_backoff(tmp_path, monkeypatch):
    _hosted_env(monkeypatch, tmp_path)
    monkeypatch.setattr(hosted, 'auth_backoff_active', lambda: False)
    monkeypatch.setattr(hosted.live, 'main', lambda: 2)
    monkeypatch.setattr(hosted, '_report_outcome', lambda: 'auth_failed')
    delays = []
    monkeypatch.setattr(hosted, 'set_auth_backoff', lambda hours: delays.append(hours))

    assert hosted.main() == 2
    assert delays == [1]
