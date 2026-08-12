"""
SQLite-Datenbank-Schema für aldi-watcher.
Speichert Usage-Logs mit provider-Spalte ('aldi', 'lidl').
"""

import sqlite3
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UsageLog:
    """Datenmodell für Usage-Log-Einträııge."""
    id: Optional[int]
    provider: str  # 'aldi' oder 'lidl'
    username: str
    data_used_mb: float
    data_total_mb: float
    threshold_mb: float
    should_recharge: bool
    recharge_triggered: bool
    error_message: Optional[str]
    created_at: datetime

    def to_tuple(self) -> tuple:
        """Konvertiert zu Tuple für SQL-Insert."""
        return (
            self.id,
            self.provider,
            self.username,
            self.data_used_mb,
            self.data_total_mb,
            self.threshold_mb,
            int(self.should_recharge),
            int(self.recharge_triggered),
            self.error_message,
            self.created_at.isoformat() if self.created_at else datetime.now().isoformat()
        )

    @classmethod
    def from_row(cls, row: tuple) -> 'UsageLog':
        """Erstellt UsageLog aus DB-Row."""
        return cls(
            id=row[0],
            provider=row[1],
            username=row[2],
            data_used_mb=row[3],
            data_total_mb=row[4],
            threshold_mb=row[5],
            should_recharge=bool(row[6]),
            recharge_triggered=bool(row[7]),
            error_message=row[8],
            created_at=datetime.fromisoformat(row[9]) if row[9] else datetime.now()
        )


class Database:
    """SQLite-Datenbank-Manager für aldi-watcher."""

    def __init__(self, db_path: str = "aldi_watcher.db"):
        self.db_path = Path(db_path)
        self._init_schema()

    def _init_schema(self):
        """Initialisiert das SQLite-Schema."""
        with sqlite3.connect(self.db_path) as conn:
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
            conn.commit()

    def log_usage(self, log: UsageLog) -> int:
        """
        Fgt einen Usage-Log-Eintrag hinzu.
        Returns die ID des neuen Eintrags.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO usage_logs 
                (provider, username, data_used_mb, data_total_mb, threshold_mb,
                 should_recharge, recharge_triggered, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, log.to_tuple()[1:])  # Skip id for INSERT
            conn.commit()
            return cursor.lastrowid

    def log_error(self, provider: str, username: str, error_message: str) -> int:
        """
        Loggt einen ERROR-Eintrag bei Provider-Ausfall.
        """
        error_log = UsageLog(
            id=None,
            provider=provider,
            username=username,
            data_used_mb=0,
            data_total_mb=0,
            threshold_mb=0,
            should_recharge=False,
            recharge_triggered=False,
            error_message=error_message,
            created_at=datetime.now()
        )
        return self.log_usage(error_log)

    def get_recent_logs(self, provider: Optional[str] = None, limit: int = 10) -> List[UsageLog]:
        """
        Ruft die neuesten Usage-Logs ab.
        """
        with sqlite3.connect(self.db_path) as conn:
            if provider:
                cursor = conn.execute("""
                    SELECT id, provider, username, data_used_mb, data_total_mb,
                           threshold_mb, should_recharge, recharge_triggered,
                           error_message, created_at
                    FROM usage_logs
                    WHERE provider = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (provider, limit))
            else:
                cursor = conn.execute("""
                    SELECT id, provider, username, data_used_mb, data_total_mb,
                           threshold_mb, should_recharge, recharge_triggered,
                           error_message, created_at
                    FROM usage_logs
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            return [UsageLog.from_row(row) for row in cursor.fetchall()]
