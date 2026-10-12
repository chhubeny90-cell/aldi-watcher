import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.database import Database
import github_journal_state as state


PHONE = '01500000000'


def operation(status='PENDING'):
    return {'recharge_id': str(uuid.uuid4()), 'status': status}


def test_public_state_contains_only_random_id_guard_status_and_retry_time():
    item = operation()
    encoded = state._encode_state([item])
    payload = json.loads(encoded)

    assert payload == {
        'version': 2,
        'unresolved': [item],
        'auth_retry_after': None,
    }
    assert PHONE.encode() not in encoded
    assert b'username' not in encoded
    assert b'provider' not in encoded
    assert b'password' not in encoded
    assert b'error' not in encoded
    assert state._parse_state(encoded) == payload


def test_version_one_state_is_upgraded_without_losing_guard():
    item = operation('UNKNOWN')
    legacy = json.dumps({'version': 1, 'unresolved': [item]}).encode()
    assert state._parse_state(legacy) == {
        'version': 2,
        'unresolved': [item],
        'auth_retry_after': None,
    }


@pytest.mark.parametrize('bad', [
    b'{}',
    b'{"version":3,"unresolved":[],"auth_retry_after":null}',
    b'{"version":2,"unresolved":"no","auth_retry_after":null}',
    b'{"version":2,"unresolved":[],"auth_retry_after":"tomorrow"}',
    b'{"version":2,"unresolved":[{"recharge_id":"not-a-uuid","status":"PENDING"}],"auth_retry_after":null}',
    b'{"version":2,"unresolved":[{"recharge_id":"00000000-0000-0000-0000-000000000000","status":"SUCCESS"}],"auth_retry_after":null}',
])
def test_invalid_remote_state_is_rejected(bad):
    with pytest.raises(RuntimeError):
        state._parse_state(bad)


def test_duplicate_operation_ids_are_rejected():
    item = operation('UNKNOWN')
    encoded = json.dumps({
        'version': 2,
        'unresolved': [item, item],
        'auth_retry_after': None,
    }).encode()
    with pytest.raises(RuntimeError, match='github_state_schema_invalid'):
        state._parse_state(encoded)


def test_restore_rehydrates_account_only_inside_local_sqlite(tmp_path, monkeypatch):
    item = operation('UNKNOWN')
    remote = {'version': 2, 'unresolved': [item], 'auth_retry_after': None}
    monkeypatch.setattr(state, '_get_state', lambda: ('remote-sha', remote))
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


def test_auth_backoff_is_active_only_before_retry_time(monkeypatch):
    now = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
    remote = {
        'version': 2,
        'unresolved': [],
        'auth_retry_after': (now + timedelta(hours=6)).isoformat().replace('+00:00', 'Z'),
    }
    monkeypatch.setattr(state, '_get_state', lambda: ('remote-sha', remote))

    assert state.auth_backoff_active(now=now) is True
    assert state.auth_backoff_active(now=now + timedelta(hours=6)) is False


def test_set_auth_backoff_preserves_unresolved_guards(monkeypatch):
    now = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)
    item = operation('PENDING')
    remote = {'version': 2, 'unresolved': [item], 'auth_retry_after': None}
    monkeypatch.setattr(state, '_get_state', lambda: ('remote-sha', remote))
    writes = []
    monkeypatch.setattr(
        state, '_put_state',
        lambda value, current_sha=None, message=None: writes.append((value.copy(), current_sha, message)),
    )

    retry = state.set_auth_backoff(hours=6, now=now)

    assert retry == '2026-10-13T02:00:00Z'
    assert writes[0][0]['unresolved'] == [item]
    assert writes[0][0]['auth_retry_after'] == retry
    assert writes[0][1] == 'remote-sha'
