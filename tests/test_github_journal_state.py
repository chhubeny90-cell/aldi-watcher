import json
import uuid

import pytest

from core.database import Database
import github_journal_state as state


PHONE = '01500000000'


def operation(status='PENDING'):
    return {'recharge_id': str(uuid.uuid4()), 'status': status}


def test_public_state_contains_only_random_id_and_guard_status():
    item = operation()
    encoded = state._encode_state([item])
    payload = json.loads(encoded)

    assert payload == {'version': 1, 'unresolved': [item]}
    assert PHONE.encode() not in encoded
    assert b'username' not in encoded
    assert b'provider' not in encoded
    assert b'password' not in encoded
    assert b'error' not in encoded
    assert state._parse_state(encoded) == [item]


@pytest.mark.parametrize('bad', [
    b'{}',
    b'{"version":2,"unresolved":[]}',
    b'{"version":1,"unresolved":"no"}',
    b'{"version":1,"unresolved":[{"recharge_id":"not-a-uuid","status":"PENDING"}]}',
    b'{"version":1,"unresolved":[{"recharge_id":"00000000-0000-0000-0000-000000000000","status":"SUCCESS"}]}',
])
def test_invalid_remote_state_is_rejected(bad):
    with pytest.raises(RuntimeError):
        state._parse_state(bad)


def test_duplicate_operation_ids_are_rejected():
    item = operation('UNKNOWN')
    encoded = json.dumps({'version': 1, 'unresolved': [item, item]}).encode()
    with pytest.raises(RuntimeError, match='github_state_schema_invalid'):
        state._parse_state(encoded)


def test_restore_rehydrates_account_only_inside_local_sqlite(tmp_path, monkeypatch):
    item = operation('UNKNOWN')
    monkeypatch.setattr(state, '_get_state', lambda: ('remote-sha', [item]))
    path = (tmp_path / 'journal.db').resolve()

    assert state.restore_journal(path, PHONE) == 'restored'
    records = Database(str(path)).get_unresolved_recharges()

    assert len(records) == 1
    assert records[0].recharge_id == item['recharge_id']
    assert records[0].status == 'UNKNOWN'
    assert records[0].provider == 'alditalk'
    assert records[0].username == PHONE


def test_first_run_initializes_empty_remote_guard_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state, '_get_state', lambda: None)
    synced = []
    monkeypatch.setattr(state, 'sync_journal', lambda path: synced.append(str(path)))
    path = (tmp_path / 'journal.db').resolve()

    assert state.restore_journal(path, PHONE) == 'initialized'
    assert Database(str(path)).get_unresolved_recharges() == []
    assert synced == [str(path)]
