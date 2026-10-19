"""Synthetic state only: no IMAP, GitHub writes, provider login or booking."""
import copy
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest

import core.mail_handoff_queue as queue
import github_journal_state as journal
import mail_actor_preflight as preflight
from core.mail_actor_handoff import HandoffBlocked, Phase
from usage_mail_bridge import _message_key, _legacy_message_key, _already_seen

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


@pytest.fixture
def stores(monkeypatch):
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'synthetic-watch-key')
    remote = {}
    writes = []

    def read(path, ref=None):
        return copy.deepcopy(remote.get(path))

    def write(path, payload, sha=None, message=None):
        current = remote.get(path)
        if (current[0] if current else None) != sha:
            raise RuntimeError('github_aux_state_conflict')
        writes.append(path)
        remote[path] = (str(len(writes)), copy.deepcopy(payload))

    monkeypatch.setattr(queue, '_read_json', read)
    monkeypatch.setattr(queue, '_write_json', write)
    monkeypatch.setattr(queue, '_trigger_state', lambda: (None, {'keys': []}))
    return remote, writes


def message(date='Mon, 19 Oct 2026 00:00:00 +0000'):
    result = EmailMessage()
    result['Message-ID'] = '<synthetic@example.invalid>'
    result['Date'] = date
    result.set_content('ALDI TALK Datenvolumen aufgebraucht')
    return result


def test_hmac_binds_message_id_and_sent_date(monkeypatch):
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'synthetic-watch-key')
    mail = message()
    key = _message_key(mail, mail.as_bytes())
    assert len(key) == 64
    assert key == _message_key(mail, mail.as_bytes())
    changed = message('Tue, 20 Oct 2026 00:00:00 +0000')
    assert key != _message_key(changed, changed.as_bytes())
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'different-synthetic-key')
    assert key != _message_key(mail, mail.as_bytes())


def test_mail_hmac_does_not_fall_back_to_password(monkeypatch):
    monkeypatch.delenv('ALDI_RECOVERY_KEY', raising=False)
    monkeypatch.setenv('ALDI_PASS', 'synthetic-password')
    with pytest.raises(RuntimeError, match='recovery_key_unavailable'):
        _message_key(message(), b'fixture')


def test_old_mail_not_retriggered(stores, monkeypatch):
    remote, _ = stores
    mail = message()
    old = _legacy_message_key(mail, mail.as_bytes())
    new = _message_key(mail, mail.as_bytes())
    old_fingerprint = queue._mac('trigger', old)
    monkeypatch.setattr(queue, '_trigger_state', lambda: ('old-sha', {'keys': [old_fingerprint]}))
    assert queue.enqueue_consumed(new, 'consumed', legacy_message_key=old) is False
    assert queue._aux_path('mail-handoff') not in remote
    # Even after eviction from the bounded old ledger, migration is permanent.
    monkeypatch.setattr(queue, '_trigger_state', lambda: ('later-sha', {'keys': []}))
    assert queue.enqueue_consumed(new, 'consumed', legacy_message_key=old) is False


def test_old_queue_identity_not_retriggered(stores):
    remote, _ = stores
    old = 'old-message-key'
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': {
        queue._fingerprint(old): {'phase': 'RESERVED', 'revision': 0},
    }})
    assert queue.enqueue_consumed('new-message-key', 'consumed', legacy_message_key=old) is False


def test_unavailable_legacy_history_blocks_enqueue(stores, monkeypatch):
    def fail():
        raise RuntimeError('legacy_unavailable')
    monkeypatch.setattr(queue, '_trigger_state', fail)
    with pytest.raises(RuntimeError, match='legacy_unavailable'):
        queue.enqueue_consumed('new', 'consumed')
    assert stores[1] == []


def record(phase='COMPLETED', days=31):
    return {'phase': phase, 'revision': 2,
            'completed_at': (NOW - timedelta(days=days)).isoformat()}


def test_archive_keeps_tombstone_before_removing_queue(stores):
    remote, writes = stores
    key = queue._fingerprint('finished')
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': {key: record()}})
    assert queue.archive_completed(now=NOW) == 1
    assert writes == [queue._aux_path('provider-journal'), queue._aux_path('mail-handoff')]
    assert key in queue._archive()[1]
    assert queue._load()[1] == {}
    assert queue.enqueue_consumed('finished', 'consumed') is False


@pytest.mark.parametrize('phase', ['RESERVED', 'IN_FLIGHT', 'QUARANTINED_UNKNOWN'])
def test_archive_never_retires_unresolved(stores, phase):
    remote, _ = stores
    key = queue._fingerprint('pending')
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': {
        key: {'phase': phase, 'revision': 2}}})
    assert queue.archive_completed(now=NOW) == 0
    assert key in queue._load()[1]


@pytest.mark.parametrize('days', [0, 29, 30])
def test_completed_retained_for_at_least_thirty_days(stores, days):
    remote, _ = stores
    key = queue._fingerprint('young')
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': {key: record(days=days)}})
    assert queue.archive_completed(now=NOW) == 0
    assert key in queue._load()[1]


def test_completed_without_timestamp_is_not_archived(stores):
    remote, _ = stores
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': {
        'a' * 64: {'phase': 'COMPLETED', 'revision': 2}}})
    assert queue.archive_completed(now=NOW) == 0


def test_crash_after_archive_write_retains_both_guards(stores, monkeypatch):
    remote, _ = stores
    key = queue._fingerprint('finished')
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': {key: record()}})
    def conflict(*args):
        raise RuntimeError('github_aux_state_conflict')
    monkeypatch.setattr(queue, '_persist', conflict)
    with pytest.raises(RuntimeError, match='github_aux_state_conflict'):
        queue.archive_completed(now=NOW)
    assert key in queue._archive()[1] and key in queue._load()[1]
    assert queue.enqueue_consumed('finished', 'consumed') is False


def test_archive_write_failure_never_removes_queue(stores, monkeypatch):
    remote, _ = stores
    key = queue._fingerprint('finished')
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': {key: record()}})
    def fail(*args, **kwargs):
        raise RuntimeError('archive_write_failed')
    monkeypatch.setattr(queue, '_write_json', fail)
    with pytest.raises(RuntimeError, match='archive_write_failed'):
        queue.archive_completed(now=NOW)
    assert key in queue._load()[1]


def test_queue_513th_event_reclaims_only_completed_slots(stores):
    remote, _ = stores
    completed = record(days=100)
    events = {queue._fingerprint(str(i)): dict(completed) for i in range(512)}
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': events})
    assert queue.enqueue_consumed('513th', 'consumed') is True
    assert len(queue._load()[1]) == 1
    assert len(queue._archive()[1]) == 512
    assert queue.enqueue_consumed('0', 'consumed') is False


def test_full_unresolved_queue_remains_blocked_without_loss(stores):
    remote, _ = stores
    events = {queue._fingerprint(str(i)): {'phase': 'RESERVED', 'revision': 0}
              for i in range(512)}
    remote[queue._aux_path('mail-handoff')] = ('1', {'version': 1, 'events': events})
    with pytest.raises(HandoffBlocked, match='queue_capacity_reached'):
        queue.enqueue_consumed('513th', 'consumed')
    assert queue._load()[1] == events


def test_snapshot_reads_queue_and_journal_at_same_commit(monkeypatch):
    seen = []
    monkeypatch.setattr(journal, '_snapshot_version', lambda: 'a' * 40)
    monkeypatch.setattr(queue, '_load', lambda ref: (seen.append(ref), {}))
    monkeypatch.setattr(journal, '_get_state', lambda ref: (seen.append(ref), {'unresolved': []}))
    version, events, state = journal.consistent_mail_snapshot()
    assert seen == ['a' * 40, 'a' * 40]
    assert version == 'a' * 40 and events == {} and state[1]['unresolved'] == []


def test_snapshot_changed_returns_blocked_exit(monkeypatch, capsys):
    versions = iter(['a' * 40, 'b' * 40])
    monkeypatch.setattr(journal, '_snapshot_version', lambda: next(versions))
    monkeypatch.setattr(queue, '_load', lambda ref: (None, {}))
    monkeypatch.setattr(journal, '_get_state', lambda ref: ('sha', {'unresolved': []}))
    assert preflight.main() == 2
    assert '"status": "BLOCKED"' in capsys.readouterr().out


@pytest.mark.parametrize('value', [None, {}, {'object': {'type': 'tree', 'sha': 'a' * 40}},
                                   {'object': {'type': 'commit', 'sha': 'bad'}}])
def test_invalid_snapshot_version_rejected(monkeypatch, value):
    monkeypatch.setattr(journal, '_request', lambda *args: value)
    with pytest.raises(RuntimeError, match='snapshot_version_invalid'):
        journal._snapshot_version()


def test_legacy_bridge_read_failure_is_not_unseen(monkeypatch):
    import usage_mail_bridge as bridge
    def fail():
        raise RuntimeError('state_unavailable')
    monkeypatch.setattr(bridge, '_trigger_state', fail)
    with pytest.raises(RuntimeError, match='state_unavailable'):
        _already_seen('key')


class WarningImap:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, *args):
        return 'OK', []

    def select(self, *args, **kwargs):
        assert kwargs['readonly'] is True
        return 'OK', []

    def search(self, *args):
        return 'OK', [b'1']

    def fetch(self, *args):
        mail = message()
        mail['Subject'] = 'ALDI TALK: 80% Datenvolumen verbraucht'
        return 'OK', [(b'1', mail.as_bytes())]


def test_old_warning_not_retriggered_after_ledger_eviction(stores, monkeypatch):
    import usage_mail_notify as monitor
    mail = message()
    mail['Subject'] = 'ALDI TALK: 80% Datenvolumen verbraucht'
    old = queue._mac('trigger', _legacy_message_key(mail, mail.as_bytes()))
    monkeypatch.setattr(queue, '_trigger_state', lambda: ('old', {'keys': [old]}))
    monkeypatch.setattr(monitor.imaplib, 'IMAP4_SSL', WarningImap)

    def forbidden(*args, **kwargs):
        pytest.fail('historical warning must not be claimed or queued')

    def poll():
        return monitor._poll_one(1, 'imap.example.invalid', 993, 'fake', 'fake',
                                 claim=forbidden, enqueue=forbidden)

    assert poll() == []
    monkeypatch.setattr(queue, '_trigger_state', lambda: ('later', {'keys': []}))
    assert poll() == []
    assert stores[1] == [queue._aux_path('legacy-trigger-history')]


def test_new_warning_claimed_once_with_real_trigger_ledger(stores, monkeypatch):
    import github_hardening_state as state
    import usage_mail_notify as monitor
    monkeypatch.setattr(state, '_read_json', queue._read_json)
    monkeypatch.setattr(state, '_write_json', queue._write_json)
    monkeypatch.setattr(queue, '_trigger_state', state._trigger_state)
    monkeypatch.setattr(monitor.imaplib, 'IMAP4_SSL', WarningImap)

    def poll():
        return monitor._poll_one(1, 'imap.example.invalid', 993, 'fake', 'fake',
                                 claim=state.claim_trigger_key,
                                 enqueue=lambda *a, **k: pytest.fail('warning queued'))

    assert poll() == [{'mailbox': 1, 'signal': '80_percent', 'actionable': False}]
    assert poll() == []
    # The second poll permanently preserved the v2 fingerprint too.
    stores[0].pop(queue._aux_path('triggers'))
    assert poll() == []


@pytest.mark.parametrize('failure', ['read', 'write'])
def test_warning_migration_failure_aborts_before_claim(stores, monkeypatch, failure):
    import usage_mail_notify as monitor
    monkeypatch.setattr(monitor.imaplib, 'IMAP4_SSL', WarningImap)

    def fail(*args, **kwargs):
        raise RuntimeError('migration_unavailable')

    if failure == 'read':
        monkeypatch.setattr(queue, '_trigger_state', fail)
    else:
        monkeypatch.setattr(queue, '_trigger_state', lambda: (None, {'keys': ['a' * 64]}))
        monkeypatch.setattr(queue, '_write_json', fail)
    with pytest.raises(RuntimeError, match='migration_unavailable'):
        monitor._poll_one(1, 'imap.example.invalid', 993, 'fake', 'fake',
                          claim=lambda *a: pytest.fail('claim after migration failure'))
