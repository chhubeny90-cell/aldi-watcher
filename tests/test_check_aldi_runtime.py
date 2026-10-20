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


def test_partial_index_is_not_a_verified_runtime_lookup(journal):
    with sqlite3.connect(journal) as conn:
        conn.execute('DROP INDEX idx_recharges_account_status')
        conn.execute('CREATE INDEX idx_recharges_account_status '
                     'ON recharges(provider, username, status, created_at) WHERE 0')
    with pytest.raises(RuntimeError, match='journal_schema_invalid'):
        inspect_runtime(str(journal))


def test_nullable_text_primary_key_is_not_a_valid_operation_identity(tmp_path, monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    path = tmp_path / 'nullable-id.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE recharges (
            recharge_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            username TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PENDING','UNKNOWN','SUCCESS','FAILED')),
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute('CREATE INDEX idx_recharges_account_status '
                     'ON recharges(provider, username, status, created_at)')
    path.chmod(0o600)
    with pytest.raises(RuntimeError, match='journal_schema_invalid'):
        inspect_runtime(str(path))


@pytest.mark.parametrize('allowed', ["'PENDING'", "'PENDING','UNKNOWN'", "'PENDING','SUCCESS','FAILED'"])
def test_runtime_and_actor_reject_incomplete_status_contract(journal, monkeypatch, allowed):
    import aldi_live_refill as live
    with sqlite3.connect(journal) as conn:
        conn.execute('DROP TABLE recharges')
        conn.execute(f'''CREATE TABLE recharges (
            recharge_id TEXT PRIMARY KEY NOT NULL, provider TEXT NOT NULL,
            username TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ({allowed})),
            error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        conn.execute('CREATE INDEX idx_recharges_account_status '
                     'ON recharges(provider, username, status, created_at)')
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(journal))
    before = journal.read_bytes()
    for check in (lambda: inspect_runtime(str(journal)), live.open_live_journal):
        with pytest.raises(RuntimeError, match='journal_schema_invalid'):
            check()
    assert journal.read_bytes() == before


@pytest.mark.parametrize('trigger', [
    'AFTER INSERT ON recharges BEGIN DELETE FROM recharges WHERE recharge_id=NEW.recharge_id; END',
    "AFTER INSERT ON recharges BEGIN UPDATE recharges SET status='SUCCESS' WHERE recharge_id=NEW.recharge_id; END",
])
def test_runtime_and_actor_reject_reservation_triggers(journal, monkeypatch, trigger):
    import aldi_live_refill as live
    from core.database import Database, RechargeLockedError
    db = Database(str(journal))
    with sqlite3.connect(journal) as conn:
        conn.execute('CREATE TRIGGER unsafe_reservation ' + trigger)
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(journal))
    before = journal.read_bytes()
    for check in (lambda: inspect_runtime(str(journal)), live.open_live_journal):
        with pytest.raises(RuntimeError, match='journal_schema_invalid'):
            check()
    assert journal.read_bytes() == before
    # Also defend against a trigger introduced after the startup schema check.
    with pytest.raises(RechargeLockedError, match='reservation_not_persisted'):
        db.begin_recharge('alditalk', 'synthetic-account')
    assert db.get_unresolved_recharges() == []


def test_live_actor_rejects_legacy_nullable_id_before_browser(journal, monkeypatch, tmp_path):
    import aldi_live_refill as live
    from unittest.mock import Mock
    with sqlite3.connect(journal) as conn:
        conn.execute('DROP TABLE recharges')
        conn.execute('''CREATE TABLE recharges (
            recharge_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
            username TEXT NOT NULL, status TEXT NOT NULL,
            error_message TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(journal))
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    monkeypatch.setenv('ALDI_EXPECTED_ACCOUNT', '01500000000')
    monkeypatch.setenv('ALDI_REQUIRED_TARGET_SUFFIX', '0000')
    monkeypatch.setattr(live.watcher, 'configure_credentials', lambda *_: True)
    monkeypatch.setattr(live.watcher, 'ALDI_ACCOUNT_USER', '01500000000')
    monkeypatch.setattr(live, 'REPORT_PATH', str(tmp_path / 'report.json'))
    browser = Mock(side_effect=AssertionError('browser must not start'))
    monkeypatch.setattr(live.watcher, 'build_driver', browser)
    before = journal.read_bytes()
    assert live.main() == 2
    browser.assert_not_called()
    assert journal.read_bytes() == before
