import json
import sqlite3

import pytest

from scripts.check_aldi_runtime import inspect_runtime, main
from scripts.init_aldi_journal import initialize_journal


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    path = tmp_path / 'journal.sqlite'
    initialize_journal(str(path))
    return path


def test_probe_reopens_backup_preserves_source_and_removes_private_copy(journal):
    before = journal.read_bytes()
    report = inspect_runtime(str(journal))
    assert report['local_backup_restore_verified'] is True
    assert report['pending'] == report['unknown'] == 0
    assert report['status'] == 'BLOCKED' and report['provider_action'] is False
    assert journal.read_bytes() == before
    assert list(journal.parent.iterdir()) == [journal]
    assert not report['host_restart_persistence_verified']


@pytest.mark.parametrize('status', ['PENDING', 'UNKNOWN'])
def test_probe_preserves_unresolved_guards_and_sanitizes_report(journal, monkeypatch, capsys, status):
    with sqlite3.connect(journal) as conn:
        conn.execute('INSERT INTO recharges VALUES (?, ?, ?, ?, NULL, ?, ?)',
                     ('private-operation', 'alditalk', 'private-account', status, 'now', 'now'))
    before = journal.read_bytes()
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(journal))
    assert main() == 2
    output = capsys.readouterr().out
    assert json.loads(output)[status.lower()] == 1
    assert 'private-operation' not in output and 'private-account' not in output
    assert str(journal) not in output
    assert journal.read_bytes() == before


def test_probe_missing_source_never_initializes_it(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'missing.sqlite'
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(path))
    assert main() == 2
    assert not path.exists()
    assert json.loads(capsys.readouterr().out)['error'] == 'private_runtime_unverified'


@pytest.mark.parametrize('kind', ['symlink', 'permissions', 'writable_parent', 'corrupt'])
def test_invalid_journal_never_claims_host_verification(journal, kind):
    path = journal
    if kind == 'symlink':
        path = journal.with_name('link.sqlite')
        path.symlink_to(journal)
    elif kind == 'permissions':
        journal.chmod(0o644)
    elif kind == 'writable_parent':
        journal.parent.chmod(0o777)
    else:
        journal.write_bytes(b'not a database')
    with pytest.raises((RuntimeError, sqlite3.DatabaseError)):
        inspect_runtime(str(path))


@pytest.mark.parametrize('runner,inside', [('github-hosted', False), ('self-hosted', True)])
def test_ephemeral_or_checkout_journal_is_rejected(journal, monkeypatch, runner, inside):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('RUNNER_ENVIRONMENT', runner)
    workspace = journal.parent if inside else journal.parent / 'checkout'
    monkeypatch.setenv('GITHUB_WORKSPACE', str(workspace))
    with pytest.raises(RuntimeError, match='durable_runner_required'):
        inspect_runtime(str(journal))


@pytest.mark.parametrize('schema', [
    """CREATE TABLE recharges (
        recharge_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
        username TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE recharges (
        recharge_id TEXT, provider TEXT, username TEXT, status TEXT,
        error_message TEXT, created_at TEXT, updated_at TEXT)""",
    """CREATE TABLE recharges (
        recharge_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
        username TEXT NOT NULL, status TEXT NOT NULL,
        error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE recharges (
        recharge_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
        username TEXT NOT NULL,
        status TEXT NOT NULL /* CHECK(status IN('PENDING','UNKNOWN','SUCCESS','FAILED')) */,
        error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
])
def test_partial_lookalike_schema_is_rejected(tmp_path, monkeypatch, schema):
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    path = tmp_path / 'invalid.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute(schema)
        conn.execute('CREATE INDEX idx_recharges_account_status '
                     'ON recharges(provider, username, status, created_at)')
    path.chmod(0o600)
    with pytest.raises(RuntimeError, match='journal_schema_invalid'):
        inspect_runtime(str(path))
