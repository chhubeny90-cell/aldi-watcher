"""Observe LITE progress; never reconcile, book, or retry provider operations.

The HTTP transport runs handlers directly. Process termination or restart needs
an explicitly configured external supervisor which owns the process. An optional
controller queues one restart of an event which has never reserved a recharge,
after this check releases the shared account lock. Only LITE reconciles bookings.
"""

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Optional, Protocol

from .store import account_lock_path


_ACCOUNT = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_ERROR = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


class RestartController(Protocol):
    def request_restart(self, event_id: str) -> bool:
        """Queue a restart after WATCHDOG releases its lock; never run LITE here."""


def _read_connection(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def _event_ref(event_id):
    # A malformed historical event ID may contain account data; do not print it.
    return hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]


class Watchdog:
    def __init__(self, database_path, account, stale_seconds=180,
                 controller: Optional[RestartController] = None):
        if not isinstance(account, str) or not _ACCOUNT.fullmatch(account):
            raise ValueError("A logical account alias is required")
        if (isinstance(stale_seconds, bool) or not isinstance(stale_seconds, (int, float))
                or not math.isfinite(stale_seconds) or stale_seconds <= 0):
            raise ValueError("stale_seconds must be finite and positive")
        self.path = Path(database_path).resolve()
        self.account = account
        self.stale_seconds = stale_seconds
        self.controller = controller
        self.lock_path = account_lock_path(self.path, account)

    def _snapshot(self, now):
        with _read_connection(self.path) as conn:
            conn.row_factory = sqlite3.Row
            events = conn.execute("""
                SELECT event_id, started_at, updated_at, recharge_id,status,action
                FROM lite_events WHERE account=? AND state='PROCESSING'
                ORDER BY started_at
            """, (self.account,)).fetchall()
            unresolved = conn.execute("""
                SELECT provider FROM recharges WHERE status IN ('PENDING','UNKNOWN')
            """).fetchall()
            latest = conn.execute("""
                SELECT event_id,status,action,error_class,updated_at
                FROM lite_events WHERE account=? AND state='COMPLETED'
                ORDER BY updated_at DESC,event_id DESC LIMIT 1
            """, (self.account,)).fetchone()
        # Conservatively retain old/unmapped ALDI reservations as blockers, as LITE does.
        pending_count = sum(
            "aldi" in (name := "".join(c for c in row["provider"].lower() if c.isalnum()))
            or name == "unknown" for row in unresolved
        )
        stale = []
        deferred = 0
        for row in events:
            # The transport deliberately leaves these mails unacknowledged so
            # its durable redelivery resumes the same event after a guard/retry.
            if row["status"] == "BUSY" and row["action"] == "RETRY" and not row["recharge_id"]:
                deferred += 1
                continue
            updated = row["updated_at"]
            if not isinstance(updated, (int, float)) or not math.isfinite(updated):
                updated = row["started_at"]
            if (isinstance(updated, (int, float)) and math.isfinite(updated)
                    and now - updated >= self.stale_seconds):
                stale.append(dict(row))
        failure = None
        if latest and (latest["status"] in {"FAILED", "UNKNOWN", "HUMAN_ACTION_REQUIRED"}
                       or latest["action"] == "HUMAN_ACTION_REQUIRED"):
            failure = {
                "event_ref": _event_ref(latest["event_id"]),
                "status": "HUMAN_ACTION_REQUIRED" if latest["action"] == "HUMAN_ACTION_REQUIRED"
                          else latest["status"],
                "error_class": latest["error_class"] if isinstance(latest["error_class"], str)
                               and _ERROR.fullmatch(latest["error_class"])
                               else ("UNCLASSIFIED" if latest["error_class"] else None),
                "completed_at": latest["updated_at"],
            }
        # One current issue with a stable reference is sufficient. Old failures
        # do not create an unbounded history or keep a recovered account unhealthy.
        return len(events), stale, pending_count, deferred, failure

    def _claim_restart(self, event_id, now):
        """Persist the one attempt before calling an external process controller."""
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lite_watchdog_actions (
                    account TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    requested_at REAL NOT NULL,
                    PRIMARY KEY(account,event_id)
                )
            """)
            cursor = conn.execute("""
                INSERT OR IGNORE INTO lite_watchdog_actions(account,event_id,requested_at)
                VALUES (?,?,?)
            """, (self.account, event_id, now))
            return cursor.rowcount == 1

    def check(self, now=None):
        now = time.time() if now is None else now
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            raise ValueError("A finite timestamp is required")
        # Read first so reporting never creates a new empty monitoring database.
        with _read_connection(self.path):
            pass
        lock = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            acquired = True
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                acquired = False
            processing, stale, unresolved, deferred, failure = self._snapshot(now)
            report = {
                "component": "WATCHDOG", "status": "HEALTHY",
                "processing_count": processing, "stale_count": len(stale),
                "unresolved_count": unresolved, "account_locked": not acquired,
                "deferred_count": deferred, "latest_completed_failure": failure,
                "stale_event_refs": [_event_ref(row["event_id"]) for row in stale],
                "action": "NONE",
            }
            if unresolved:
                report.update(status="RECONCILE_REQUIRED", action="LITE_RECONCILE_REQUIRED")
            elif not acquired:
                report.update(status="STALLED_LOCKED" if stale else "RUNNING")
                if stale:
                    report["action"] = "SUPERVISOR_CHECK_OWNED_PROCESS"
            elif stale:
                # Even a terminal reservation needs LITE to finish the same event.
                if any(row["recharge_id"] for row in stale):
                    report.update(status="RECOVERY_REQUIRED", action="LITE_RECONCILE_REQUIRED")
                elif self.controller is None:
                    report.update(status="STALLED", action="SUPERVISOR_CHECK_OWNED_PROCESS")
                else:
                    target = stale[0]
                    if not self._claim_restart(target["event_id"], now):
                        report.update(status="RESTART_ALREADY_REQUESTED")
                    else:
                        # This callback must queue work; LITE takes the same lock later.
                        try:
                            accepted = self.controller.request_restart(target["event_id"]) is True
                        except Exception:
                            accepted = False
                        report.update(status="RESTART_REQUESTED" if accepted else "RESTART_REQUEST_FAILED",
                                      action="RESTART_ONCE")
            elif deferred:
                report.update(status="WAITING_FOR_REDELIVERY", action="MAIL_REDELIVERY")
            elif not processing and failure:
                if failure["status"] == "UNKNOWN":
                    report.update(status="RECONCILE_REQUIRED", action="LITE_RECONCILE_REQUIRED")
                elif failure["status"] == "HUMAN_ACTION_REQUIRED":
                    report.update(status="HUMAN_ACTION_REQUIRED", action="HUMAN_ACTION_REQUIRED")
                else:
                    report.update(status="COMPLETED_FAILED", action="REVIEW_FAILURE")
            return report
        finally:
            os.close(lock)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--stale-seconds", type=float, default=180)
    args = parser.parse_args(argv)
    try:
        report = Watchdog(args.db, args.account, args.stale_seconds).check()
    except (OSError, sqlite3.Error, ValueError):
        report = {"component": "WATCHDOG", "status": "CONFIG_ERROR", "action": "NONE"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"HEALTHY", "RUNNING", "WAITING_FOR_REDELIVERY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
