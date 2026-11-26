"""Transactionally safe SQLite journal for future provider adapters.

No phone numbers or credentials enter this database. Every possible booking
must reserve PENDING durably before invoking a provider. UNKNOWN blocks forever
until a separately verified, operation-bound reconciliation exists.
"""

from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Optional
import hashlib
import os
import re
import sqlite3
import uuid

from .models import (
    AccountSnapshot, Blocked, CompletionProof, OfferProof, Provider,
    RefillRecord, RefillStatus,
)

_ID = re.compile(r"^[a-z][a-z0-9_-]{2,39}$")
_CODE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_MAX_GB = Decimal("1000000")
ACTIVE = ("PENDING", "UNKNOWN")


def _utc(value: Optional[datetime] = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _ts(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _decimal(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or not (0 <= value <= _MAX_GB):
        raise ValueError("finite, nonnegative Decimal GB value required")
    return value


def _alias(account_id: str) -> str:
    if not isinstance(account_id, str) or not _ID.fullmatch(account_id):
        raise ValueError("use a non-sensitive alias: 3-40 lowercase letters/digits/_/-")
    if re.search(r"\d{7,}", account_id):
        raise ValueError("an account alias must not contain a telephone number")
    return account_id


class StateStore:
    """One persistent SQLite file shared by all workers on one host."""

    def __init__(self, path: str | Path, *, cooldown_seconds: int = 1800,
                 freshness_seconds: int = 180):
        if cooldown_seconds < 60 or freshness_seconds < 1:
            raise ValueError("invalid safety timeouts")
        self.path = Path(path).expanduser().absolute()
        self.cooldown_seconds = cooldown_seconds
        self.freshness_seconds = freshness_seconds
        if self.path.is_symlink():
            raise ValueError("database symlink is prohibited")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            if self.path.parent.stat().st_mode & 0o077:
                raise PermissionError("database directory must be private (chmod 700)")
        if self.path.exists() and not self.path.is_file():
            raise ValueError("database path is not a regular file")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        if os.name == "posix":
            self.path.chmod(0o600)
        with closing(self._connection()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL CHECK (provider IN ('aldi', 'lidl'))
                );
                CREATE TABLE IF NOT EXISTS account_state (
                    account_id TEXT PRIMARY KEY REFERENCES accounts(account_id),
                    remaining_gb TEXT,
                    last_checked_at TEXT,
                    last_refill_at TEXT,
                    cooldown_until TEXT
                );
                CREATE TABLE IF NOT EXISTS refill_operations (
                    operation_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES accounts(account_id),
                    status TEXT NOT NULL CHECK(status IN
                        ('PENDING','UNKNOWN','SUCCESS','FAILED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    receipt_sha256 TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uniq_unresolved_account
                  ON refill_operations(account_id)
                  WHERE status IN ('PENDING','UNKNOWN');
                CREATE TABLE IF NOT EXISTS error_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL REFERENCES accounts(account_id),
                    error_code TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_refill_history
                  ON refill_operations(account_id, created_at);
            """)
        if os.name == "posix":
            self.path.chmod(0o600)

    def _connection(self) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise ValueError("database symlink is prohibited")
        conn = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()
        finally:
            conn.close()

    def register_account(self, account_id: str, provider: Provider) -> None:
        account_id = _alias(account_id)
        provider = Provider(provider)
        with self._write() as conn:
            conn.execute("INSERT OR IGNORE INTO accounts(account_id, provider) VALUES (?,?)",
                         (account_id, provider.value))
            row = conn.execute(
                "SELECT provider FROM accounts WHERE account_id=?", (account_id,)
            ).fetchone()
            if row["provider"] != provider.value:
                raise ValueError("provider mismatch for existing alias")
            conn.execute("INSERT OR IGNORE INTO account_state(account_id) VALUES (?)",
                         (account_id,))

    def record_observation(self, account_id: str, remaining_gb: Decimal,
                           *, at: Optional[datetime] = None) -> None:
        account_id = _alias(account_id)
        value = _decimal(remaining_gb)
        timestamp = _utc(at)
        if timestamp > datetime.now(timezone.utc) + timedelta(seconds=5):
            raise ValueError("future observation")
        with self._write() as conn:
            row = conn.execute(
                "SELECT last_checked_at FROM account_state WHERE account_id=?",
                (account_id,),
            ).fetchone()
            if row is None:
                raise KeyError("unknown account alias")
            if row["last_checked_at"] and datetime.fromisoformat(row["last_checked_at"]) > timestamp:
                raise Blocked("stale observation cannot replace newer state")
            conn.execute("""
                UPDATE account_state
                SET remaining_gb=?, last_checked_at=?
                WHERE account_id=?
            """, (format(value, "f"), _ts(timestamp), account_id))

    def snapshot(self, account_id: str) -> AccountSnapshot:
        account_id = _alias(account_id)
        with closing(self._connection()) as conn:
            row = conn.execute("""
                SELECT a.account_id,a.provider,s.remaining_gb,s.last_checked_at,
                       s.last_refill_at,s.cooldown_until
                FROM accounts a JOIN account_state s USING(account_id)
                WHERE a.account_id=?
            """, (account_id,)).fetchone()
        if row is None:
            raise KeyError("unknown account alias")
        return AccountSnapshot(
            account_id=row["account_id"], provider=Provider(row["provider"]),
            remaining_gb=Decimal(row["remaining_gb"]) if row["remaining_gb"] is not None else None,
            last_checked_at=row["last_checked_at"],
            last_refill_at=row["last_refill_at"], cooldown_until=row["cooldown_until"],
        )

    def reserve_refill(self, account_id: str, proof: OfferProof,
                       *, at: Optional[datetime] = None) -> str:
        account_id = _alias(account_id)
        now = _utc(at)
        if proof.account_id != account_id or not proof.eligible:
            raise Blocked("missing account, price, entitlement or permission proof")
        with self._write() as conn:
            row = conn.execute("""
                SELECT remaining_gb,last_checked_at,cooldown_until
                FROM account_state WHERE account_id=?
            """, (account_id,)).fetchone()
            if row is None:
                raise KeyError("unknown account alias")
            checked = (datetime.fromisoformat(row["last_checked_at"])
                       if row["last_checked_at"] else None)
            if checked is None or checked > now or (now - checked).total_seconds() > self.freshness_seconds:
                raise Blocked("volume observation is missing or stale")
            if row["remaining_gb"] is None or Decimal(row["remaining_gb"]) >= Decimal("1"):
                raise Blocked("remaining allowance is not below 1 GB")
            if row["cooldown_until"] and datetime.fromisoformat(row["cooldown_until"]) > now:
                raise Blocked("account cooldown is active")
            unresolved = conn.execute("""
                SELECT 1 FROM refill_operations
                WHERE account_id=? AND status IN ('PENDING','UNKNOWN') LIMIT 1
            """, (account_id,)).fetchone()
            if unresolved:
                raise Blocked("unresolved operation blocks every further refill")
            operation_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO refill_operations
                (operation_id,account_id,status,created_at,updated_at)
                VALUES (?,?,'PENDING',?,?)
            """, (operation_id, account_id, _ts(now), _ts(now)))
            return operation_id

    def mark_unknown(self, operation_id: str, *, at: Optional[datetime] = None) -> None:
        """Call after ANY ambiguous side effect; never infer FAILED from a timeout."""
        with self._write() as conn:
            row = conn.execute(
                "SELECT status FROM refill_operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError("unknown operation")
            if row["status"] in ACTIVE:
                conn.execute("""
                    UPDATE refill_operations SET status='UNKNOWN',updated_at=?
                    WHERE operation_id=?
                """, (_ts(_utc(at)), operation_id))
            # Terminal outcomes are never reopened by a late timeout.

    def reconcile_success(self, proof: CompletionProof, *,
                          at: Optional[datetime] = None) -> None:
        """Only the future provider adapter may supply authoritative evidence.

        A changed allowance or a generic success toast is not evidence.
        """
        if not proof.verified or not 8 <= len(proof.receipt_identifier) <= 256:
            raise Blocked("operation-bound official receipt required")
        account_id = _alias(proof.account_id)
        now = _utc(at)
        digest = hashlib.sha256(proof.receipt_identifier.encode("utf-8")).hexdigest()
        with self._write() as conn:
            row = conn.execute("""
                SELECT account_id,status FROM refill_operations WHERE operation_id=?
            """, (proof.operation_id,)).fetchone()
            if row is None or row["account_id"] != account_id:
                raise Blocked("receipt has no matching operation")
            if row["status"] == "SUCCESS":
                return
            if row["status"] not in ACTIVE:
                raise Blocked("terminal operation cannot be changed")
            conn.execute("""
                UPDATE refill_operations
                SET status='SUCCESS',updated_at=?,receipt_sha256=?
                WHERE operation_id=?
            """, (_ts(now), digest, proof.operation_id))
            conn.execute("""
                UPDATE account_state SET last_refill_at=?,cooldown_until=?
                WHERE account_id=?
            """, (_ts(now), _ts(now + timedelta(seconds=self.cooldown_seconds)), account_id))

    def history(self, account_id: str, limit: int = 100) -> list[RefillRecord]:
        account_id = _alias(account_id)
        if not 1 <= limit <= 1000:
            raise ValueError("invalid history limit")
        with closing(self._connection()) as conn:
            rows = conn.execute("""
                SELECT operation_id,account_id,status,created_at,updated_at,receipt_sha256
                FROM refill_operations WHERE account_id=? ORDER BY created_at DESC LIMIT ?
            """, (account_id, limit)).fetchall()
        return [RefillRecord(
            operation_id=r["operation_id"], account_id=r["account_id"],
            status=RefillStatus(r["status"]), created_at=r["created_at"],
            updated_at=r["updated_at"], receipt_sha256=r["receipt_sha256"],
        ) for r in rows]

    def log_error(self, account_id: str, code: str, *,
                  at: Optional[datetime] = None) -> None:
        account_id = _alias(account_id)
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise ValueError("store sanitized error codes only")
        with self._write() as conn:
            conn.execute("""
                INSERT INTO error_events(account_id,error_code,recorded_at)
                VALUES (?,?,?)
            """, (account_id, code, _ts(_utc(at))))
