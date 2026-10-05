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


def test_begin_recharge_blocks_duplicate(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    first = db.begin_recharge("fake", "user")
    with pytest.raises(RechargeLockedError):
        db.begin_recharge("fake", "user")
    assert db.get_unresolved_recharges("fake", "user")[0].recharge_id == first


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
