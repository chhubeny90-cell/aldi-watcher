"""Offline process-level checks for the existing SQLite reservation boundary.

These tests call Database directly, without BaseWatcher, account_lock, browser
code or provider requests. Each spawned process opens the same local journal.
"""

import multiprocessing as mp
import sqlite3

import pytest

from core.database import Database, RechargeLockedError


PROVIDER = "synthetic-provider"
ACCOUNT = "synthetic-account"


def _reserve_worker(db_path, barrier, results):
    database = Database(db_path)
    barrier.wait()
    try:
        recharge_id = database.begin_recharge(PROVIDER, ACCOUNT)
    except RechargeLockedError:
        results.put(("blocked", None))
    else:
        results.put(("reserved", recharge_id))


def _status_worker(db_path, recharge_id, status, barrier, results):
    database = Database(db_path)
    barrier.wait()
    actual = database.set_recharge_status(recharge_id, status)
    results.put((status, actual))


def _run_workers(target, arguments):
    """Start all workers before releasing the shared SQLite race boundary."""
    context = mp.get_context("spawn")
    barrier = context.Barrier(len(arguments) + 1, timeout=15)
    results = context.Queue()
    workers = [
        context.Process(target=target, args=(*args, barrier, results))
        for args in arguments
    ]
    started = []
    try:
        for worker in workers:
            worker.start()
            started.append(worker)
        barrier.wait()
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0
        return [results.get(timeout=5) for _ in workers]
    finally:
        for worker in started:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)
            worker.close()
        results.close()
        results.join_thread()


def _recharge_rows(db_path):
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT recharge_id, provider, username, status FROM recharges"
        ).fetchall()


def test_direct_parallel_reservations_create_exactly_one_pending(tmp_path):
    db_path = str(tmp_path / "journal.sqlite")
    Database(db_path)

    outcomes = _run_workers(_reserve_worker, [(db_path,)] * 4)

    winners = [recharge_id for outcome, recharge_id in outcomes if outcome == "reserved"]
    assert len(winners) == 1
    assert outcomes.count(("blocked", None)) == 3
    assert _recharge_rows(db_path) == [(winners[0], PROVIDER, ACCOUNT, "PENDING")]
    # No outer account flock participated in the SQLite reservation race.
    assert list(tmp_path.glob("*.lock")) == []
    with pytest.raises(RechargeLockedError):
        Database(db_path).begin_recharge(PROVIDER, ACCOUNT)
    assert _recharge_rows(db_path) == [(winners[0], PROVIDER, ACCOUNT, "PENDING")]


def test_sqlite_timeout_rolls_back_and_allows_reservation_after_release(tmp_path):
    db_path = str(tmp_path / "journal.sqlite")
    database = Database(db_path, timeout=0.05)

    with sqlite3.connect(db_path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            database.begin_recharge(PROVIDER, ACCOUNT)
        assert _recharge_rows(db_path) == []
        blocker.rollback()

    recharge_id = database.begin_recharge(PROVIDER, ACCOUNT)
    assert _recharge_rows(db_path) == [(recharge_id, PROVIDER, ACCOUNT, "PENDING")]
    with pytest.raises(RechargeLockedError):
        Database(db_path).begin_recharge(PROVIDER, ACCOUNT)
    assert _recharge_rows(db_path) == [(recharge_id, PROVIDER, ACCOUNT, "PENDING")]


@pytest.mark.parametrize("terminal_status", ["SUCCESS", "FAILED"])
def test_parallel_unknown_cannot_replace_terminal_status(tmp_path, terminal_status):
    db_path = str(tmp_path / "journal.sqlite")
    recharge_id = Database(db_path).begin_recharge(PROVIDER, ACCOUNT)

    outcomes = dict(_run_workers(_status_worker, [
        (db_path, recharge_id, terminal_status),
        (db_path, recharge_id, "UNKNOWN"),
    ]))

    assert outcomes[terminal_status] == terminal_status
    assert outcomes["UNKNOWN"] in {"UNKNOWN", terminal_status}
    assert _recharge_rows(db_path) == [(recharge_id, PROVIDER, ACCOUNT, terminal_status)]
    # Reopen after both processes exited, then explicitly exercise a late result.
    reopened = Database(db_path)
    assert reopened.set_recharge_status(recharge_id, "UNKNOWN") == terminal_status
    assert reopened.get_unresolved_recharges(PROVIDER, ACCOUNT) == []
    assert _recharge_rows(db_path) == [(recharge_id, PROVIDER, ACCOUNT, terminal_status)]
    assert list(tmp_path.glob("*.lock")) == []
