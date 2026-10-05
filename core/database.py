"""SQLite persistence for usage logs and idempotent recharge operations."""

import sqlite3
import uuid
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
from pathlib import Path


ACTIVE_RECHARGE_STATUSES = ("PENDING", "UNKNOWN")


@dataclass
class UsageLog:
    id: Optional[int]
    provider: str
    username: str
    data_used_mb: float
    data_total_mb: float
    threshold_mb: float
    should_recharge: bool
    recharge_triggered: bool
    error_message: Optional[str]
    created_at: datetime

    def to_tuple(self) -> tuple:
        return (
            self.id, self.provider, self.username, self.data_used_mb,
            self.data_total_mb, self.threshold_mb, int(self.should_recharge),
            int(self.recharge_triggered), self.error_message,
            self.created_at.isoformat() if self.created_at else datetime.now().isoformat()
        )

    @classmethod
    def from_row(cls, row: tuple) -> "UsageLog":
        return cls(
            id=row[0], provider=row[1], username=row[2], data_used_mb=row[3],
            data_total_mb=row[4], threshold_mb=row[5],
            should_recharge=bool(row[6]), recharge_triggered=bool(row[7]),
            error_message=row[8],
            created_at=datetime.fromisoformat(row[9]) if row[9] else datetime.now()
        )


@dataclass
class RechargeRecord:
    recharge_id: str
    provider: str
    username: str
    status: str
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None


class RechargeLockedError(RuntimeError):
    pass


class Database:
    def __init__(self, db_path: str = "aldi_watcher.db", timeout: float = 10.0):
        self.db_path = Path(db_path)
        self.timeout = timeout
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=self.timeout)
        conn.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    username TEXT NOT NULL,
                    data_used_mb REAL NOT NULL,
                    data_total_mb REAL NOT NULL,
                    threshold_mb REAL NOT NULL,
                    should_recharge INTEGER NOT NULL,
                    recharge_triggered INTEGER NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_provider_created
                ON usage_logs(provider, created_at)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recharges (
                    recharge_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    username TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','UNKNOWN','SUCCESS','FAILED')),
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recharges_account_status
                ON recharges(provider, username, status, created_at)
            """)

    def log_usage(self, log: UsageLog) -> int:
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO usage_logs
                (provider, username, data_used_mb, data_total_mb, threshold_mb,
                 should_recharge, recharge_triggered, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, log.to_tuple()[1:])
            return cursor.lastrowid

    def log_error(self, provider: str, username: str, error_message: str) -> int:
        return self.log_usage(UsageLog(
            None, provider, username, 0, 0, 0, False, False,
            error_message, datetime.now()
        ))

    def get_recent_logs(self, provider: Optional[str] = None, limit: int = 10) -> List[UsageLog]:
        with self._connect() as conn:
            if provider:
                cursor = conn.execute("""
                    SELECT id, provider, username, data_used_mb, data_total_mb,
                           threshold_mb, should_recharge, recharge_triggered,
                           error_message, created_at
                    FROM usage_logs WHERE provider = ?
                    ORDER BY created_at DESC LIMIT ?
                """, (provider, limit))
            else:
                cursor = conn.execute("""
                    SELECT id, provider, username, data_used_mb, data_total_mb,
                           threshold_mb, should_recharge, recharge_triggered,
                           error_message, created_at
                    FROM usage_logs ORDER BY created_at DESC LIMIT ?
                """, (limit,))
            return [UsageLog.from_row(row) for row in cursor.fetchall()]

    def begin_recharge(self, provider: str, username: str) -> str:
        recharge_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""
                SELECT recharge_id, status FROM recharges
                WHERE provider = ? AND username = ?
                  AND status IN ('PENDING','UNKNOWN')
                ORDER BY created_at DESC LIMIT 1
            """, (provider, username)).fetchone()
            if row:
                conn.rollback()
                raise RechargeLockedError(
                    f"Recharge blocked by existing {row[1]} operation {row[0]}"
                )
            conn.execute("""
                INSERT INTO recharges
                (recharge_id, provider, username, status, error_message, created_at, updated_at)
                VALUES (?, ?, ?, 'PENDING', NULL, ?, ?)
            """, (recharge_id, provider, username, now, now))
            conn.commit()
            return recharge_id
        finally:
            conn.close()

    def set_recharge_status(self, recharge_id: str, status: str, error_message: Optional[str] = None):
        if status not in {"PENDING", "UNKNOWN", "SUCCESS", "FAILED"}:
            raise ValueError(f"Invalid recharge status: {status}")
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE recharges SET status = ?, error_message = ?, updated_at = ?
                WHERE recharge_id = ?
            """, (status, error_message, datetime.now().isoformat(), recharge_id))
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown recharge_id: {recharge_id}")

    def get_unresolved_recharges(self, provider: Optional[str] = None, username: Optional[str] = None):
        query = """
            SELECT recharge_id, provider, username, status, created_at, updated_at, error_message
            FROM recharges WHERE status IN ('PENDING','UNKNOWN')
        """
        params = []
        if provider is not None:
            query += " AND provider = ?"
            params.append(provider)
        if username is not None:
            query += " AND username = ?"
            params.append(username)
        query += " ORDER BY created_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            RechargeRecord(
                recharge_id=r[0], provider=r[1], username=r[2], status=r[3],
                created_at=datetime.fromisoformat(r[4]),
                updated_at=datetime.fromisoformat(r[5]), error_message=r[6]
            ) for r in rows
        ]
