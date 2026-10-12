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
