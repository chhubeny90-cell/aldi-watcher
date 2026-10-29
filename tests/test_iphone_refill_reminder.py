import sqlite3
from pathlib import Path

import pytest

from scripts.iphone_refill_reminder import notify

def test_rejects_empty_event(tmp_path):
    with pytest.raises(ValueError):
        notify("", tmp_path / "notifications.db")

def test_does_not_repeat_unknown_delivery(tmp_path, monkeypatch):
    db = tmp_path / "notifications.db"
    monkeypatch.delenv("ALDI_NOTIFY_SMTP_HOST", raising=False)
    with pytest.raises(RuntimeError):
        notify("stable-mail-message-id-123", db)
    assert notify("stable-mail-message-id-123", db) is False
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT state FROM notifications").fetchone()[0] == "unknown"

def test_rejects_line_breaks_in_id(tmp_path):
    with pytest.raises(ValueError):
        notify("id\nunsafe", tmp_path / "notifications.db")
