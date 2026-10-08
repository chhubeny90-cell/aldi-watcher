"""Watchdog crash supervision and completed-event analytics need no provider."""

import ast
import fcntl
import json
import multiprocessing as mp
import os
from pathlib import Path
import sqlite3

import pytest

from lite.models import MailEvent, ProcessResult
from lite.pro import Report, main as pro_main
from lite.store import EventStore, account_lock_path
from lite.watchdog import Watchdog, main as watchdog_main


def event(store, identifier, kind="warning80", account="primary", mailbox="mailbox",
          received=100, started=200, updated=220, completed=False, status="NO_ACTION",
          error=None):
    value = MailEvent(identifier, mailbox, identifier, received, kind, account)
    store.claim_event(value)
    if completed:
        store.finish(identifier, ProcessResult(status, "CHECK", error_class=error))
    with store._connect() as conn:
        conn.execute("UPDATE lite_events SET started_at=?,updated_at=? WHERE event_id=?",
                     (started, updated, identifier))
    return value


def rows(store):
    with store._connect() as conn:
        return (
            conn.execute("SELECT * FROM lite_events ORDER BY event_id").fetchall(),
            conn.execute("SELECT * FROM recharges ORDER BY recharge_id").fetchall(),
        )


class Controller:
    def __init__(self, raises=False):
        self.calls = []
        self.raises = raises

    def request_restart(self, event_id):
        self.calls.append(event_id)
        if self.raises:
            raise RuntimeError("private-password@example.invalid")
        return True


def test_watchdog_completed_event_is_healthy_and_rows_unchanged(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "finished", completed=True)
    before = rows(store)
    result = Watchdog(store.db_path, "primary", stale_seconds=30).check(now=1000)
    assert result["status"] == "HEALTHY"
    assert result["stale_count"] == result["processing_count"] == 0
    assert rows(store) == before


def test_watchdog_uses_last_progress_and_only_its_account(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "fresh", updated=990)
    event(store, "other", account="secondary", updated=1)
    assert Watchdog(store.db_path, "primary", 30).check(now=1000)["status"] == "HEALTHY"


@pytest.mark.parametrize("status,action,expected", [
    ("FAILED", "CHECK", "COMPLETED_FAILED"),
    ("UNKNOWN", "REFILL", "RECONCILE_REQUIRED"),
    ("BLOCKED", "HUMAN_ACTION_REQUIRED", "HUMAN_ACTION_REQUIRED"),
    ("HUMAN_ACTION_REQUIRED", "CHECK", "HUMAN_ACTION_REQUIRED"),
])
def test_completed_failure_is_reported_without_mutation_or_restart(tmp_path, status, action, expected):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "private-mail@example.invalid", completed=True, status=status,
          error="password=private@example.invalid")
    with store._connect() as conn:
        conn.execute("UPDATE lite_events SET action=?", (action,))
    controller = Controller()
    watchdog = Watchdog(store.db_path, "primary", 30, controller)
    before = rows(store)
    first = watchdog.check(now=1000)
    second = watchdog.check(now=1100)
    assert first["status"] == expected
    assert first["latest_completed_failure"] == second["latest_completed_failure"]
    assert first["latest_completed_failure"]["error_class"] == "UNCLASSIFIED"
    assert "private" not in json.dumps(first)
    assert controller.calls == []
    assert rows(store) == before
    with store._connect() as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='lite_watchdog_actions'").fetchone() is None


def test_new_completed_success_clears_old_failure_without_alert_history(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "failed", completed=True, status="FAILED", updated=200)
    event(store, "recovered", completed=True, status="SUCCESS", updated=220)
    report = Watchdog(store.db_path, "primary", 30).check(now=1000)
    assert report["status"] == "HEALTHY"
    assert report["latest_completed_failure"] is None


def test_deferred_mail_waits_for_redelivery_and_never_looks_like_crashed_process(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "deferred")
    store.defer("deferred", "RECENT_SUCCESS")
    with store._connect() as conn:
        conn.execute("UPDATE lite_events SET updated_at=220 WHERE event_id='deferred'")
    controller = Controller()
    report = Watchdog(store.db_path, "primary", 30, controller).check(now=1000)
    assert report["status"] == "WAITING_FOR_REDELIVERY"
    assert report["deferred_count"] == 1
    assert report["stale_count"] == 0
    assert controller.calls == []


def test_stale_locked_process_is_alerted_without_controller_action(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "private-mail-id@example.invalid")
    controller = Controller()
    descriptor = os.open(account_lock_path(store.db_path, "primary"), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        before = rows(store)
        result = Watchdog(store.db_path, "primary", 30, controller).check(now=1000)
        assert result["status"] == "STALLED_LOCKED"
        assert result["action"] == "SUPERVISOR_CHECK_OWNED_PROCESS"
        assert result["account_locked"] is True
        assert controller.calls == []
        assert "private-mail-id" not in json.dumps(result)
        assert rows(store) == before
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("status", ["PENDING", "UNKNOWN"])
def test_unresolved_recharge_requires_lite_and_is_never_changed(tmp_path, status):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "pending")
    recharge = store.reserve("pending", "aldi_talk", "primary", 0)
    if status == "UNKNOWN":
        store.set_recharge_status(recharge, status)
    with store._connect() as conn:
        conn.execute("UPDATE lite_events SET updated_at=220 WHERE event_id='pending'")
    controller = Controller()
    before = rows(store)
    result = Watchdog(store.db_path, "primary", 30, controller).check(now=1000)
    assert result["status"] == "RECONCILE_REQUIRED"
    assert result["unresolved_count"] == 1
    assert result["action"] == "LITE_RECONCILE_REQUIRED"
    assert controller.calls == []
    assert rows(store) == before


def test_legacy_unmapped_aldi_pending_blocks_restart(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "event")
    store.begin_recharge("alditalk", "legacy-account")
    controller = Controller()
    assert Watchdog(store.db_path, "primary", 30, controller).check(now=1000)["status"] == "RECONCILE_REQUIRED"
    assert controller.calls == []


def test_completed_reservation_with_unfinished_event_requires_lite_recovery(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "event")
    recharge = store.reserve("event", "aldi_talk", "primary", 0)
    store.set_recharge_status(recharge, "SUCCESS")
    with store._connect() as conn:
        conn.execute("UPDATE lite_events SET updated_at=220 WHERE event_id='event'")
    controller = Controller()
    result = Watchdog(store.db_path, "primary", 30, controller).check(now=1000)
    assert result["status"] == "RECOVERY_REQUIRED"
    assert controller.calls == []


@pytest.mark.parametrize("raises", [False, True])
def test_restart_attempt_is_persisted_once_even_when_controller_raises(tmp_path, raises):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "event")
    before = rows(store)
    controller = Controller(raises)
    result = Watchdog(store.db_path, "primary", 30, controller).check(now=1000)
    assert result["status"] == ("RESTART_REQUEST_FAILED" if raises else "RESTART_REQUESTED")
    assert "private-password" not in json.dumps(result)
    reopened = Watchdog(store.db_path, "primary", 30, controller)
    assert reopened.check(now=1100)["status"] == "RESTART_ALREADY_REQUESTED"
    assert controller.calls == ["event"]
    assert rows(store) == before


def _stalled_child(db_path, ready, release, reserve):
    store = EventStore(db_path)
    descriptor = os.open(account_lock_path(db_path, "primary"), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    event(store, "interrupted")
    if reserve:
        store.reserve("interrupted", "aldi_talk", "primary", 0)
    with store._connect() as conn:
        conn.execute("UPDATE lite_events SET updated_at=220 WHERE event_id='interrupted'")
    ready.set()
    release.wait(30)
    os.close(descriptor)


@pytest.mark.skipif(os.name == "nt", reason="Process fencing uses POSIX flock")
@pytest.mark.parametrize("reserve", [False, True])
def test_killed_child_and_reopened_state_preserve_crash_boundary(tmp_path, reserve):
    db_path = str(tmp_path / "state.sqlite")
    EventStore(db_path)
    context = mp.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_stalled_child, args=(db_path, ready, release, reserve))
    process.start()
    try:
        assert ready.wait(10)
        process.terminate()
        process.join(10)
        assert process.exitcode != 0
        store = EventStore(db_path)
        before = rows(store)
        controller = Controller()
        report = Watchdog(db_path, "primary", 30, controller).check(now=1000)
        assert report["account_locked"] is False
        if reserve:
            assert report["status"] == "RECONCILE_REQUIRED"
            assert controller.calls == []
            assert store.get_unresolved_recharges()[0].status == "PENDING"
        else:
            assert report["status"] == "RESTART_REQUESTED"
            assert controller.calls == ["interrupted"]
            assert store.get_unresolved_recharges() == []
        assert rows(store) == before
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)


def test_pro_aggregates_completed_events_and_mail_intervals_separately(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "warning", received=10, started=1000, updated=1001, completed=True)
    event(store, "exhausted", "exhausted", received=70, started=1100, updated=1200,
          completed=True, status="FAILED", error="TimeoutError")
    event(store, "unfinished", received=100, started=1201, updated=9999)
    before = rows(store)
    report = Report(store.db_path, "primary").summarize()
    assert report["completed_count"] == 2
    assert report["statuses"] == {"FAILED": 1, "NO_ACTION": 1}
    assert report["error_classes"] == {"TimeoutError": 1}
    assert report["event_latency_seconds"]["mean"] == 50.5
    assert report["warning_to_exhausted_mail_seconds"]["mean"] == 60
    assert rows(store) == before


def test_pro_never_pairs_different_accounts_or_mailboxes(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "warning-a", received=10, account="primary", completed=True)
    event(store, "exhausted-b", "exhausted", received=70, account="secondary", completed=True)
    event(store, "exhausted-c", "exhausted", received=80, mailbox="other-mailbox", completed=True)
    assert Report(store.db_path).summarize()["warning_to_exhausted_mail_seconds"]["count"] == 0


def test_pro_pairs_latest_warning_once_and_redacts_unclassified_errors(tmp_path):
    store = EventStore(str(tmp_path / "state.sqlite"))
    event(store, "warning-old", received=10, completed=True)
    event(store, "warning-new", received=20, completed=True)
    event(store, "exhausted-first", "exhausted", received=70, completed=True,
          error="password=private@example.invalid")
    event(store, "exhausted-repeat", "exhausted", received=80, completed=True)
    report = Report(store.db_path).summarize()
    assert report["warning_to_exhausted_mail_seconds"]["count"] == 1
    assert report["warning_to_exhausted_mail_seconds"]["mean"] == 50
    assert report["error_classes"] == {"UNCLASSIFIED": 1}
    assert "private" not in json.dumps(report)


def test_pro_readonly_mode_does_not_create_missing_database(tmp_path, capsys):
    path = tmp_path / "missing.sqlite"
    assert pro_main(["--db", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "CONFIG_ERROR"
    assert not path.exists()


def test_watchdog_missing_database_is_classified_without_creation(tmp_path, capsys):
    path = tmp_path / "missing.sqlite"
    assert watchdog_main(["--db", str(path), "--account", "primary"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "CONFIG_ERROR"
    assert not path.exists()


def test_pro_has_only_standard_library_imports():
    import lite.pro
    syntax = ast.parse(Path(lite.pro.__file__).read_text())
    modules = {node.module.split(".")[0] for node in ast.walk(syntax)
               if isinstance(node, ast.ImportFrom) and node.module}
    modules.update(alias.name.split(".")[0] for node in ast.walk(syntax)
                   if isinstance(node, ast.Import) for alias in node.names)
    assert modules <= {"argparse", "collections", "json", "math", "pathlib", "re", "sqlite3", "statistics"}
