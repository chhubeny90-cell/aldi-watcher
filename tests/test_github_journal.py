import base64
import os
import sqlite3

import pytest
from cryptography.fernet import Fernet

from core.database import RechargeLockedError
from core.github_journal import GitHubJournal


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeGitHubSession:
    def __init__(self):
        self.ciphertext = None
        self.sha = None
        self.revision = 0
        self.force_conflict = False
        self.put_payloads = []

    def get(self, url, **kwargs):
        if self.ciphertext is None:
            return FakeResponse(404)
        return FakeResponse(200, {
            'sha': self.sha,
            'content': base64.b64encode(self.ciphertext).decode(),
        })

    def put(self, url, **kwargs):
        payload = kwargs['json']
        self.put_payloads.append(payload)
        if self.force_conflict:
            self.force_conflict = False
            return FakeResponse(409)
        expected = payload.get('sha')
        if self.ciphertext is None:
            if expected is not None:
                return FakeResponse(422)
            status = 201
        else:
            if expected != self.sha:
                return FakeResponse(409)
            status = 200
        self.ciphertext = base64.b64decode(payload['content'])
        self.revision += 1
        self.sha = f'sha-{self.revision}'
        return FakeResponse(status, {'content': {'sha': self.sha}})


def _journal(tmp_path, session, key):
    return GitHubJournal(
        'owner/repo',
        'test-token',
        key.decode(),
        session=session,
        temp_dir=tmp_path,
    )


def _decrypt_to_path(tmp_path, ciphertext, key):
    path = tmp_path / 'decrypted.sqlite'
    path.write_bytes(Fernet(key).decrypt(ciphertext))
    return path


@pytest.mark.skipif(os.name != 'posix', reason='live journal requires POSIX semantics')
def test_bootstrap_stores_only_encrypted_sqlite(tmp_path):
    key = Fernet.generate_key()
    session = FakeGitHubSession()
    journal = _journal(tmp_path, session, key)
    try:
        assert session.sha == 'sha-1'
        assert session.ciphertext is not None
        plaintext = Fernet(key).decrypt(session.ciphertext)
        assert plaintext.startswith(b'SQLite format 3\x00')
        assert session.ciphertext != plaintext
        assert journal.db_path.stat().st_mode & 0o777 == 0o600
    finally:
        journal.cleanup()


@pytest.mark.skipif(os.name != 'posix', reason='live journal requires POSIX semantics')
def test_begin_recharge_is_remote_pending_before_return(tmp_path):
    key = Fernet.generate_key()
    session = FakeGitHubSession()
    journal = _journal(tmp_path, session, key)
    try:
        recharge_id = journal.begin_recharge('alditalk', '01500000000')
        assert session.sha == 'sha-2'
        assert b'01500000000' not in session.ciphertext
        remote = _decrypt_to_path(tmp_path, session.ciphertext, key)
        with sqlite3.connect(remote) as conn:
            row = conn.execute(
                'SELECT recharge_id, provider, username, status FROM recharges'
            ).fetchone()
        assert row == (recharge_id, 'alditalk', '01500000000', 'PENDING')
    finally:
        journal.cleanup()


@pytest.mark.skipif(os.name != 'posix', reason='live journal requires POSIX semantics')
def test_remote_compare_and_set_conflict_blocks_reservation(tmp_path):
    key = Fernet.generate_key()
    session = FakeGitHubSession()
    journal = _journal(tmp_path, session, key)
    try:
        session.force_conflict = True
        with pytest.raises(RechargeLockedError, match='compare_and_set_conflict'):
            journal.begin_recharge('alditalk', '01500000000')
        remote = _decrypt_to_path(tmp_path, session.ciphertext, key)
        with sqlite3.connect(remote) as conn:
            count = conn.execute('SELECT COUNT(*) FROM recharges').fetchone()[0]
        assert count == 0
    finally:
        journal.cleanup()


@pytest.mark.skipif(os.name != 'posix', reason='live journal requires POSIX semantics')
def test_status_transition_is_durable_and_visible_to_fresh_runner(tmp_path):
    key = Fernet.generate_key()
    session = FakeGitHubSession()
    first = _journal(tmp_path, session, key)
    recharge_id = first.begin_recharge('alditalk', '01500000000')
    assert first.set_recharge_status(recharge_id, 'UNKNOWN') == 'UNKNOWN'
    first.cleanup()

    second = _journal(tmp_path, session, key)
    try:
        unresolved = second.get_unresolved_recharges('alditalk', '01500000000')
        assert len(unresolved) == 1
        assert unresolved[0].recharge_id == recharge_id
        assert unresolved[0].status == 'UNKNOWN'
    finally:
        second.cleanup()


@pytest.mark.skipif(os.name != 'posix', reason='live journal requires POSIX semantics')
def test_wrong_key_fails_closed_without_replacing_remote_state(tmp_path):
    session = FakeGitHubSession()
    correct = Fernet.generate_key()
    journal = _journal(tmp_path, session, correct)
    original = session.ciphertext
    journal.cleanup()

    with pytest.raises(RuntimeError, match='decryption_failed'):
        _journal(tmp_path, session, Fernet.generate_key())
    assert session.ciphertext == original
