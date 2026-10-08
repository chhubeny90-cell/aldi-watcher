"""LITE event journal extending the existing shared recharge database."""

import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from core.database import Database, RechargeLockedError
from .models import Confirmation, MailEvent, ProcessResult


class EventCollisionError(ValueError):
    pass


class AccountBindingError(ValueError):
    error_class = "account_alias_mismatch"


class ReservationBlockedError(RechargeLockedError):
    def __init__(self, code: str):
        self.error_class = code
        super().__init__(code)


def account_lock_path(database_path, account: Optional[str] = None) -> Path:
    """Global ALDI fence: this deployment supports one physical ALDI account."""
    path = Path(database_path).resolve()
    return path.parent / (path.name + ".aldi.lock")


class EventStore(Database):
    def _init_schema(self):
        super()._init_schema()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lite_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lite_events (
                    event_id TEXT PRIMARY KEY,
                    mailbox TEXT NOT NULL,
                    mail_id TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    kind TEXT NOT NULL,
                    account TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('PROCESSING','COMPLETED')),
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    status TEXT,
                    action TEXT,
                    recharge_id TEXT,
                    error_class TEXT,
                    booking_id TEXT,
                    check_attempts INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(mailbox, mail_id)
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(lite_events)")}
            if "check_attempts" not in columns:
                conn.execute("ALTER TABLE lite_events ADD COLUMN check_attempts INTEGER NOT NULL DEFAULT 0")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lite_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    step TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES lite_events(event_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lite_progress_event
                ON lite_progress(event_id, id)
            """)

    @staticmethod
    def _bind_account(conn, account: str):
        row = conn.execute("SELECT value FROM lite_meta WHERE key='aldi_account_alias'").fetchone()
        if row and row[0] != account:
            raise AccountBindingError("account_alias_mismatch")
        aliases = conn.execute("SELECT DISTINCT account FROM lite_events").fetchall()
        if any(alias[0] != account for alias in aliases):
            raise AccountBindingError("account_alias_mismatch")
        if row is None:
            conn.execute("INSERT INTO lite_meta(key,value) VALUES ('aldi_account_alias',?)", (account,))

    def bind_account(self, account: str):
        """Bind once in SQLite; switching an alias requires deliberate state review."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._bind_account(conn, account)

    def _dict_row(self, query, parameters):
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, parameters).fetchone()
            return dict(row) if row else None

    def get_event(self, event_id: str):
        return self._dict_row("SELECT * FROM lite_events WHERE event_id = ?", (event_id,))

    def list_events(self, limit: int = 100, account: Optional[str] = None):
        query = "SELECT * FROM lite_events"
        parameters = []
        if account is not None:
            query += " WHERE account = ?"
            parameters.append(account)
        query += " ORDER BY started_at DESC LIMIT ?"
        parameters.append(max(1, min(int(limit), 10000)))
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, parameters).fetchall()]

    def claim_event(self, event: MailEvent):
        """Deduplicate in SQLite, resuming only an abandoned in-flight event.

        Callers must hold the account process lock before calling this method.
        """
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM lite_events
                WHERE event_id = ? OR (mailbox = ? AND mail_id = ?)
            """, (event.event_id, event.mailbox, event.mail_id)).fetchall()
            if rows:
                # Never reuse an ID to impersonate another mailbox/message/account.
                if len(rows) != 1:
                    raise EventCollisionError("Event identity collision")
                row = dict(rows[0])
                if (row["mailbox"], row["mail_id"], row["account"], row["kind"], row["received_at"]) != (
                    event.mailbox, event.mail_id, event.account, event.kind, event.received_at
                ):
                    raise EventCollisionError("Event identity collision")
                return row, row["state"] == "COMPLETED"
            conn.execute("""
                INSERT INTO lite_events
                (event_id,mailbox,mail_id,received_at,kind,account,state,started_at,updated_at)
                VALUES (?,?,?,?,?,?,'PROCESSING',?,?)
            """, (event.event_id, event.mailbox, event.mail_id, event.received_at,
                  event.kind, event.account, now, now))
            conn.execute("""
                INSERT INTO lite_progress(event_id, recorded_at, step) VALUES (?,?,'EVENT_RECEIVED')
            """, (event.event_id, now))
        return self.get_event(event.event_id), False

    def progress(self, event_id: str, step: str):
        now = time.time()
        with self._connect() as conn:
            conn.execute("INSERT INTO lite_progress(event_id,recorded_at,step) VALUES (?,?,?)",
                         (event_id, now, step))
            conn.execute("UPDATE lite_events SET updated_at = ? WHERE event_id = ?", (now, event_id))

    def start_check(self, event_id: str) -> int:
        """Persist the read attempt before any login/inspection takes place."""
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                UPDATE lite_events SET check_attempts=check_attempts+1,updated_at=?
                WHERE event_id=? AND state='PROCESSING'
            """, (now, event_id))
            row = conn.execute("SELECT check_attempts FROM lite_events WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise KeyError("Unknown event")
            conn.execute("INSERT INTO lite_progress(event_id,recorded_at,step) VALUES (?,?,'PROVIDER_CHECK_STARTED')",
                         (event_id, now))
            return row[0]

    def has_check_retry(self, event_id: str) -> bool:
        return self._dict_row("""
            SELECT id FROM lite_progress WHERE event_id=? AND step='TRANSIENT_CHECK_RETRY' LIMIT 1
        """, (event_id,)) is not None

    def finish(self, event_id: str, result: ProcessResult, booking_id: Optional[str] = None):
        now = time.time()
        with self._connect() as conn:
            conn.execute("""
                UPDATE lite_events
                SET state='COMPLETED',updated_at=?,status=?,action=?,
                    recharge_id=COALESCE(?,recharge_id),error_class=?,booking_id=COALESCE(?,booking_id)
                WHERE event_id=?
            """, (now, result.status, result.action, result.recharge_id,
                  result.error_class, booking_id, event_id))
            conn.execute("INSERT INTO lite_progress(event_id,recorded_at,step) VALUES (?,?,'COMPLETED')",
                         (event_id, now))
        return result

    def defer(self, event_id: str, error_class: str, step="RECENT_SUCCESS_GUARD"):
        """Keep a cooldown event claim resumable; its mail must not be acknowledged."""
        now = time.time()
        with self._connect() as conn:
            conn.execute("""
                UPDATE lite_events SET updated_at=?,status='BUSY',action='RETRY',error_class=?
                WHERE event_id=? AND state='PROCESSING'
            """, (now, error_class, event_id))
            conn.execute("INSERT INTO lite_progress(event_id,recorded_at,step) VALUES (?,?,?)",
                         (event_id, now, step))
        return ProcessResult("BUSY", "RETRY", error_class=error_class)

    def reserve(self, event_id: str, provider: str, account: str, guard_seconds: float) -> str:
        """Atomically reserve in the shared recharge table and link the event.

        The original Database.begin_recharge commits before returning its ID;
        this extension keeps that ID and its triggering event in one transaction.
        """
        recharge_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._bind_account(conn, account)
            active_rows = conn.execute("""
                SELECT provider,username FROM recharges WHERE status IN ('PENDING','UNKNOWN')
            """).fetchall()
            for existing_provider, existing_account in active_rows:
                normalized = "".join(char for char in existing_provider.lower() if char.isalnum())
                if "aldi" in normalized or normalized == "unknown":
                    if (existing_provider, existing_account) != (provider, account):
                        raise ReservationBlockedError("legacy_unresolved_requires_account_mapping")
                    raise ReservationBlockedError("UNRESOLVED_RECHARGE")
            if guard_seconds > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=guard_seconds)).isoformat()
                recent = conn.execute("""
                    SELECT recharge_id FROM recharges WHERE provider=? AND username=?
                    AND status='SUCCESS' AND updated_at>=? LIMIT 1
                """, (provider, account, cutoff)).fetchone()
                if recent:
                    raise ReservationBlockedError("RECENT_SUCCESS")
            conn.execute("""
                INSERT INTO recharges
                (recharge_id,provider,username,status,error_message,created_at,updated_at)
                VALUES (?,?,?,'PENDING',NULL,?,?)
            """, (recharge_id, provider, account, now, now))
            cursor = conn.execute("""
                UPDATE lite_events SET recharge_id=?,updated_at=?
                WHERE event_id=? AND state='PROCESSING' AND recharge_id IS NULL
            """, (recharge_id, time.time(), event_id))
            if cursor.rowcount != 1:
                raise ReservationBlockedError("EVENT_ALREADY_RESERVED")
            conn.execute("INSERT INTO lite_progress(event_id,recorded_at,step) VALUES (?,?,'BOOKING_STARTED')",
                         (event_id, time.time()))
        return recharge_id

    def apply_confirmation(self, recharge_id: str, confirmation: Confirmation):
        status = self.set_recharge_status(recharge_id, confirmation.status, confirmation.error_class)
        # The committed shared transaction is authoritative if a previous result won.
        with self._connect() as conn:
            conn.execute("""
                UPDATE lite_events SET booking_id=COALESCE(?,booking_id),updated_at=?
                WHERE recharge_id=?
            """, (confirmation.booking_id, time.time(), recharge_id))
        return status

    def event_for_recharge(self, recharge_id: str):
        return self._dict_row("SELECT * FROM lite_events WHERE recharge_id=?", (recharge_id,))

    def recharge_status(self, recharge_id: str):
        return self._dict_row("SELECT status,error_message FROM recharges WHERE recharge_id=?", (recharge_id,))

    def has_unmapped_aldi_recharge(self, provider: str, account: str) -> bool:
        # Old AldiTalkWatcher also inherited the base provider name UNKNOWN.
        for record in self.get_unresolved_recharges():
            normalized = "".join(char for char in record.provider.lower() if char.isalnum())
            if ("aldi" in normalized or normalized == "unknown") and (
                record.provider != provider or record.username != account
            ):
                return True
        return False

    def has_recent_success(self, provider: str, account: str, guard_seconds: float) -> bool:
        if guard_seconds <= 0:
            return False
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=guard_seconds)).isoformat()
        return self._dict_row("""
            SELECT recharge_id FROM recharges WHERE provider=? AND username=?
            AND status='SUCCESS' AND updated_at>=? LIMIT 1
        """, (provider, account, cutoff)) is not None
