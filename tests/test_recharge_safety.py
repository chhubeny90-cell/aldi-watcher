import asyncio
import multiprocessing as mp
import os
import sqlite3
from pathlib import Path

import pytest

from core.database import Database, RechargeLockedError
from plugins.base_watcher import BaseWatcher


class FakeWatcher(BaseWatcher):
    def __init__(self, db, counter_file=None, crash=False, status="UNKNOWN"):
        super().__init__("user", "pw", 500, dry_run=False, database=db)
        self.counter_file = counter_file
        self.crash = crash
        self.status = status

    @property
    def provider_name(self):
        return "fake"

    async def check_usage(self):
        return {"used_mb": 600, "total_mb": 1000}

    async def trigger_recharge(self, recharge_id=None):
        if self.counter_file:
            with open(self.counter_file, "a", encoding="utf-8") as f:
                f.write(recharge_id + "\n")
                f.flush()
                os.fsync(f.fileno())
        if self.crash:
            os._exit(23)
        return True

    async def check_recharge_status(self, recharge_id):
        return self.status


def _worker(db_path, counter_file, start_event):
    db = Database(db_path)
    watcher = FakeWatcher(db, counter_file)
    start_event.wait()
    asyncio.run(watcher.run())


def _crash_worker(db_path, counter_file):
    db = Database(db_path)
    watcher = FakeWatcher(db, counter_file, crash=True)
    asyncio.run(watcher.run())


def _crash_before_call_worker(db_path, counter_file):
    class CrashAfterCommitDatabase(Database):
        def begin_recharge(self, *args, **kwargs):
            super().begin_recharge(*args, **kwargs)
            os._exit(24)
    asyncio.run(FakeWatcher(CrashAfterCommitDatabase(db_path), counter_file).run())


def _recovery_worker(db_path, counter_file, status, started, release):
    class DelayedRecoveryWatcher(FakeWatcher):
        async def check_recharge_status(self, recharge_id):
            started.set()
            assert release.wait(10)
            return self.status
    asyncio.run(DelayedRecoveryWatcher(Database(db_path), counter_file, status=status).recover_pending())


def test_begin_recharge_blocks_duplicate(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    first = db.begin_recharge("fake", "user")
    with pytest.raises(RechargeLockedError):
        db.begin_recharge("fake", "user")
    assert db.get_unresolved_recharges("fake", "user")[0].recharge_id == first


def test_success_does_not_permanently_block_later_recharge(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    first = db.begin_recharge("fake", "user")
    db.set_recharge_status(first, "SUCCESS")
    second = db.begin_recharge("fake", "user")
    assert second != first


def test_timeout_becomes_unknown_and_never_retries(tmp_path):
    class TimeoutWatcher(FakeWatcher):
        async def trigger_recharge(self, recharge_id=None):
            raise asyncio.TimeoutError("provider timed out")

    db = Database(str(tmp_path / "db.sqlite"))
    watcher = TimeoutWatcher(db)
    result = asyncio.run(watcher.run())
    assert result.recharge_status == "UNKNOWN"
    assert len(db.get_unresolved_recharges("fake", "user")) == 1
    second = asyncio.run(watcher.run())
    assert second.recharge_status == "BLOCKED"


def test_recovery_unknown_stays_blocked(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    recharge_id = db.begin_recharge("fake", "user")
    watcher = FakeWatcher(db, status="UNKNOWN")
    asyncio.run(watcher.recover_pending())
    rows = db.get_unresolved_recharges("fake", "user")
    assert rows[0].recharge_id == recharge_id
    assert rows[0].status == "UNKNOWN"


def test_multiprocess_only_one_external_call(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    counter_file = str(tmp_path / "calls.txt")
    Database(db_path)
    ctx = mp.get_context("spawn")
    start = ctx.Event()
    processes = [
        ctx.Process(target=_worker, args=(db_path, counter_file, start))
        for _ in range(4)
    ]
    for p in processes:
        p.start()
    start.set()
    for p in processes:
        p.join(15)
        assert p.exitcode == 0
    calls = Path(counter_file).read_text().splitlines()
    assert len(calls) == 1


@pytest.mark.skipif(os.name == "nt", reason="crash semantics tested on POSIX CI")
def test_crash_after_external_call_leaves_pending_and_recovery_does_not_rebook(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    counter_file = str(tmp_path / "calls.txt")
    Database(db_path)
    ctx = mp.get_context("spawn")
    p = ctx.Process(target=_crash_worker, args=(db_path, counter_file))
    p.start()
    p.join(15)
    assert p.exitcode == 23

    db = Database(db_path)
    pending = db.get_unresolved_recharges("fake", "user")
    assert len(pending) == 1
    assert pending[0].status == "PENDING"

    recovery = FakeWatcher(db, counter_file, status="UNKNOWN")
    asyncio.run(recovery.recover_pending())
    assert len(Path(counter_file).read_text().splitlines()) == 1
    assert db.get_unresolved_recharges("fake", "user")[0].status == "UNKNOWN"


@pytest.mark.skipif(os.name == "nt", reason="POSIX crash boundary")
def test_crash_after_pending_commit_before_call_stays_blocked(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    counter_file = str(tmp_path / "calls.txt")
    Database(db_path)
    ctx = mp.get_context("spawn")
    process = ctx.Process(target=_crash_before_call_worker, args=(db_path, counter_file))
    process.start()
    process.join(15)
    assert process.exitcode == 24
    assert not Path(counter_file).exists()
    db = Database(db_path)
    assert db.get_unresolved_recharges("fake", "user")[0].status == "PENDING"
    result = asyncio.run(FakeWatcher(db, counter_file).run())
    assert result.recharge_status == "BLOCKED"
    assert not Path(counter_file).exists()


@pytest.mark.parametrize("outcome", ["SUCCESS", "FAILED"])
def test_recovery_resolves_terminal_outcomes_without_booking(tmp_path, outcome):
    db = Database(str(tmp_path / "db.sqlite"))
    recharge_id = db.begin_recharge("fake", "user")
    counter_file = tmp_path / "calls.txt"
    result = asyncio.run(FakeWatcher(db, str(counter_file), status=outcome).recover_pending())
    assert result == [(recharge_id, outcome)]
    assert db.get_unresolved_recharges("fake", "user") == []
    assert not counter_file.exists()
    assert db.set_recharge_status(recharge_id, "UNKNOWN") == outcome


def test_stale_multiprocess_recovery_cannot_undo_success(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    counter_file = str(tmp_path / "calls.txt")
    db = Database(db_path)
    recharge_id = db.begin_recharge("fake", "user")
    ctx = mp.get_context("spawn")
    unknown_started, success_started = ctx.Event(), ctx.Event()
    unknown_release, success_release = ctx.Event(), ctx.Event()
    stale = ctx.Process(target=_recovery_worker, args=(db_path, counter_file, "UNKNOWN", unknown_started, unknown_release))
    success = ctx.Process(target=_recovery_worker, args=(db_path, counter_file, "SUCCESS", success_started, success_release))
    for process in (stale, success):
        process.start()
    assert unknown_started.wait(10)
    assert success_started.wait(10)
    success_release.set()
    success.join(15)
    unknown_release.set()
    stale.join(15)
    assert success.exitcode == stale.exitcode == 0
    assert db.set_recharge_status(recharge_id, "UNKNOWN") == "SUCCESS"
    assert db.get_unresolved_recharges("fake", "user") == []
    assert not Path(counter_file).exists()


def test_sqlite_lock_timeout_prevents_external_call(tmp_path):
    db_path = str(tmp_path / "db.sqlite")
    counter_file = tmp_path / "calls.txt"
    db = Database(db_path, timeout=.05)
    with sqlite3.connect(db_path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        result = asyncio.run(FakeWatcher(db, str(counter_file)).run())
        assert result.success is False
        assert result.error_message == "OperationalError"
        assert not counter_file.exists()
        blocker.rollback()
    assert db.get_unresolved_recharges("fake", "user") == []


def test_unknown_cannot_return_to_pending(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    recharge_id = db.begin_recharge("fake", "user")
    db.set_recharge_status(recharge_id, "UNKNOWN")
    with pytest.raises(ValueError, match="UNKNOWN"):
        db.set_recharge_status(recharge_id, "PENDING")
