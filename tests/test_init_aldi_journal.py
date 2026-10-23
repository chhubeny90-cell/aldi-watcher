import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts.init_aldi_journal import initialize_journal


@pytest.mark.skipif(os.name != "posix", reason="live journal requires POSIX")
def test_initialize_journal_creates_private_schema(tmp_path):
    path = tmp_path / "state" / "journal.sqlite"
    path.parent.mkdir()

    result = initialize_journal(str(path))

    assert result == {
        "journal_ready": True,
        "created": True,
        "permissions": "0600",
        "schema_verified": True,
    }
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(recharges)")}
    assert {"recharge_id", "provider", "username", "status"}.issubset(columns)


@pytest.mark.skipif(os.name != "posix", reason="live journal requires POSIX")
def test_initialize_journal_validates_existing_database(tmp_path):
    path = tmp_path / "journal.sqlite"
    first = initialize_journal(str(path))
    second = initialize_journal(str(path))
    assert first["created"] is True
    assert second["created"] is False
    assert second["journal_ready"] is True


@pytest.mark.skipif(os.name != "posix", reason="live journal requires POSIX")
def test_direct_cli_invocation_works_from_repo_root(tmp_path):
    path = tmp_path / "journal.sqlite"
    repo_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/init_aldi_journal.py", str(path)],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    result = json.loads(completed.stdout)
    assert result["journal_ready"] is True
    assert result["created"] is True
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="live journal requires POSIX")
def test_initialize_journal_rejects_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="absolute_path_required"):
        initialize_journal("journal.sqlite")


@pytest.mark.skipif(os.name != "posix", reason="live journal requires POSIX")
def test_initialize_journal_rejects_symlink(tmp_path):
    target = tmp_path / "target.sqlite"
    target.touch()
    target.chmod(0o600)
    link = tmp_path / "journal.sqlite"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="journal_symlink_rejected"):
        initialize_journal(str(link))


@pytest.mark.skipif(os.name != "posix", reason="live journal requires POSIX")
def test_initialize_journal_rejects_broad_permissions(tmp_path):
    path = tmp_path / "journal.sqlite"
    initialize_journal(str(path))
    path.chmod(0o640)
    with pytest.raises(RuntimeError, match="journal_permissions_must_be_0600"):
        initialize_journal(str(path))


@pytest.mark.skipif(os.name != "posix", reason="live journal requires POSIX")
def test_initialize_journal_rejects_writable_parent(tmp_path):
    parent = tmp_path / "shared"
    parent.mkdir(mode=0o700)
    parent.chmod(0o777)
    path = parent / "journal.sqlite"
    with pytest.raises(RuntimeError, match="journal_parent_must_not_be_group_or_world_writable"):
        initialize_journal(str(path))


def test_initializer_rejects_legacy_schema_without_normalization_or_history_loss(tmp_path):
    from core.journal_validation import RECHARGES_TABLE_SQL
    path = tmp_path / 'legacy.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute(RECHARGES_TABLE_SQL.replace('PRIMARY KEY NOT NULL', 'PRIMARY KEY'))
        conn.execute("INSERT INTO recharges VALUES ('old-operation','alditalk','private-account','UNKNOWN',NULL,'now','now')")
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='journal_schema_invalid'):
        initialize_journal(str(path))
    assert path.read_bytes() == before
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT recharge_id,status FROM recharges').fetchall() == [('old-operation','UNKNOWN')]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='usage_logs'").fetchall() == []
