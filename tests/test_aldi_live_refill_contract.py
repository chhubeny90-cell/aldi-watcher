import pytest
import json
import sqlite3
from dataclasses import replace
from unittest.mock import Mock

from core.database import Database
from core.aldi_completion import evaluate_completion
from core.aldi_provider_exchange import ProviderExchange
from tests.test_aldi_live_refill import _setup, _eligible, _unavailable

import aldi_live_refill_contract as contract


def _completed(operation='tx-1'):
    return evaluate_completion(
        request_payload={'offerId': 'offer-1', 'subscriptionId': 'sub-1', 'resourceId': 'r1'},
        response_payload={'transactionId': operation, 'status': 'COMPLETED'},
        http_status=200, account_binding_verified=True, request_was_update_unlimited=True,
    )


def test_provider_operation_cannot_complete_two_local_recharges(tmp_path):
    db = Database(str(tmp_path / 'journal.db'))
    first = db.begin_recharge('alditalk', 'account-1')
    contract._persist_provider_evidence(db, first, _completed())
    db.set_recharge_status(first, 'SUCCESS')
    second = db.begin_recharge('alditalk', 'account-1')
    # Re-open the journal to prove the uniqueness guard survives process state.
    reopened = Database(db.db_path)
    with pytest.raises(sqlite3.IntegrityError):
        contract._persist_provider_evidence(reopened, second, _completed())
    assert reopened.get_unresolved_recharges()[0].recharge_id == second
    assert reopened.get_unresolved_recharges()[0].status == 'PENDING'


def test_provider_evidence_is_idempotent_but_cannot_be_rebound(tmp_path):
    db = Database(str(tmp_path / 'journal.db'))
    rid = db.begin_recharge('alditalk', 'account-1')
    evidence = _completed()
    contract._persist_provider_evidence(db, rid, evidence)
    contract._persist_provider_evidence(db, rid, evidence)
    with pytest.raises(RuntimeError, match='rebinding_rejected'):
        contract._persist_provider_evidence(db, rid, replace(evidence, provider_operation_id='tx-other'))
    with db._connect() as conn:
        assert conn.execute('SELECT provider_operation_id FROM recharge_provider_evidence').fetchall() == [('tx-1',)]


def test_completed_provider_exchange_updates_runner_report_and_journal(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    click = Mock()
    monkeypatch.setattr(contract.live, '_trusted_click', click)
    monkeypatch.setattr(contract.live, '_action_kind', lambda *_: 'book')
    observed = ProviderExchange(
        request_payload={'offerId': 'offer-1', 'subscriptionId': 'sub-1', 'resourceId': 'r1'},
        response_payload={'transactionId': 'tx-1', 'status': 'COMPLETED'},
        http_status=200, request_was_update_unlimited=True,
        request_id_present=True, response_body_available=True,
    )
    monkeypatch.setattr(contract, 'observe_update_unlimited_exchange', lambda *_a, **_k: observed)
    assert contract.main() == 0
    click.assert_called_once_with(driver, control)
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['outcome'] == 'refill_verified'
    assert report['successful_refills'] == 1
    assert report['cycles'][0]['verified'] is True
    assert report['cycles'][0]['confirmation'] == 'provider_receipt'
    db = Database(str(tmp_path / 'journal.sqlite'))
    assert db.get_unresolved_recharges() == []
    with db._connect() as conn:
        assert conn.execute('SELECT status FROM recharges').fetchall() == [('SUCCESS',)]


def test_replayed_exchange_keeps_new_recharge_unresolved(monkeypatch, tmp_path):
    control = Mock()
    _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    db = Database(str(tmp_path / 'journal.sqlite'))
    old = db.begin_recharge('alditalk', '01500000000')
    contract._persist_provider_evidence(db, old, _completed())
    db.set_recharge_status(old, 'SUCCESS')
    # Simulate an older success so the cross-run cooldown is not the blocker.
    with db._connect() as conn:
        conn.execute("UPDATE recharges SET updated_at='2020-01-01T00:00:00', created_at='2020-01-01T00:00:00'")
    monkeypatch.setattr(contract.live, '_trusted_click', Mock())
    monkeypatch.setattr(contract.live, '_action_kind', lambda *_: 'book')
    observed = ProviderExchange(
        {'offerId': 'offer-1', 'subscriptionId': 'sub-1', 'resourceId': 'r1'},
        {'transactionId': 'tx-1', 'status': 'COMPLETED'}, 200, True, True, True,
    )
    monkeypatch.setattr(contract, 'observe_update_unlimited_exchange', lambda *_a, **_k: observed)
    assert contract.main() == 2
    unresolved = db.get_unresolved_recharges()
    assert len(unresolved) == 1
    assert unresolved[0].status in {'PENDING', 'UNKNOWN'}


def test_main_resets_state_and_restores_process_global_hooks(monkeypatch):
    original_click = contract.live._trusted_click
    original_bound = contract.live._bound_status
    original_set = contract.live.Database.set_recharge_status
    original_limit = contract.live.MAX_REFILLS_PER_RUN

    contract._STATE.update({
        "pre_binding": ("stale", "stale"),
        "post_binding": ("stale", "stale"),
        "exchange": object(),
        "clicks": 9,
        "contract": object(),
    })

    observed = {}

    def fake_live_main():
        observed["limit"] = contract.live.MAX_REFILLS_PER_RUN
        observed["state"] = dict(contract._STATE)
        assert contract.live._trusted_click is not original_click
        assert contract.live._bound_status is not original_bound
        assert contract.live.Database.set_recharge_status is not original_set
        return 0

    monkeypatch.setattr(contract.live, "main", fake_live_main)

    assert contract.main() == 0
    assert observed["limit"] == 1
    assert observed["state"] == {
        "pre_binding": None,
        "post_binding": None,
        "exchange": None,
        "clicks": 0,
        "contract": None,
    }
    assert contract.live._trusted_click is original_click
    assert contract.live._bound_status is original_bound
    assert contract.live.Database.set_recharge_status is original_set
    assert contract.live.MAX_REFILLS_PER_RUN == original_limit


def test_main_restores_hooks_and_limit_when_runner_raises(monkeypatch):
    original_click = contract.live._trusted_click
    original_bound = contract.live._bound_status
    original_set = contract.live.Database.set_recharge_status
    original_limit = contract.live.MAX_REFILLS_PER_RUN

    def explode():
        raise RuntimeError("simulated")

    monkeypatch.setattr(contract.live, "main", explode)

    with pytest.raises(RuntimeError, match="simulated"):
        contract.main()

    assert contract.live._trusted_click is original_click
    assert contract.live._bound_status is original_bound
    assert contract.live.Database.set_recharge_status is original_set
    assert contract.live.MAX_REFILLS_PER_RUN == original_limit

