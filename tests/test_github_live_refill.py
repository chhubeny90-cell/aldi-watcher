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
