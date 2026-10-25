"""Persistent read-only IMAP sensor. No provider login, booking or dispatch.

This ledger is sensor progress only. It never replaces the private booking
journal, remote event history, receipt verifier or account-binding contract.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile


class SensorBlocked(RuntimeError):
    pass


def utc_timestamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError
        return stamp.timestamp()
    except (AttributeError, TypeError, ValueError):
        raise SensorBlocked('cutoff_unverified') from None


def fingerprint(key, label, *values):
    if not isinstance(key, str) or not key.strip() or key != key.strip():
        raise SensorBlocked('recovery_key_unavailable_or_ambiguous')
    material = json.dumps([label, *values], separators=(',', ':'), ensure_ascii=True)
    return hmac.new(key.encode(), material.encode(), hashlib.sha256).hexdigest()


def positive_uid(value):
    if isinstance(value, bytes):
        value = value.decode('ascii', errors='strict')
    if not isinstance(value, str) or re.fullmatch(r'[1-9][0-9]{0,9}', value) is None:
        raise SensorBlocked('imap_uid_invalid')
    result = int(value)
    if result > 4294967295:
        raise SensorBlocked('imap_uid_invalid')
    return result


def _private_file(path):
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or any(parent.is_symlink() for parent in path.parents)):
        raise SensorBlocked('existing_sensor_ledger_required')
    if os.name == 'posix' and (path.stat().st_mode & 0o777 != 0o600
                              or path.parent.stat().st_mode & 0o022):
        raise SensorBlocked('private_sensor_permissions_required')


class SensorStore:
    """Every UID observation and cursor update commits in one SQLite transaction."""
    @classmethod
    def initialize(cls, path, key, cutoff):
        path = Path(path)
        cutoff = utc_timestamp(cutoff)
        check = fingerprint(key, 'sensor-key-check-v1')
        if (not path.is_absolute() or not path.parent.is_dir()
                or any(p.is_symlink() for p in path.parents)
                or os.name == 'posix' and path.parent.stat().st_mode & 0o022):
            raise SensorBlocked('private_sensor_directory_required')
        # Explicit initialization only; never replace an existing or lost history.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript('''
                CREATE TABLE meta(version INTEGER NOT NULL, key_check TEXT NOT NULL, cutoff REAL NOT NULL);
                CREATE TABLE mailboxes(
                    mailbox TEXT PRIMARY KEY NOT NULL, epoch INTEGER NOT NULL,
                    last_uid INTEGER NOT NULL, failures INTEGER NOT NULL DEFAULT 0,
                    due REAL NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE messages(
                    mailbox TEXT NOT NULL, message TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('IGNORED','WARNING','BLOCKED')),
                    PRIMARY KEY(mailbox,message));
                CREATE TABLE deliveries(
                    mailbox TEXT NOT NULL, epoch INTEGER NOT NULL, uid INTEGER NOT NULL,
                    message TEXT NOT NULL, PRIMARY KEY(mailbox,epoch,uid));
            ''')
            conn.execute('INSERT INTO meta VALUES (1,?,?)', (check, cutoff))
            conn.commit()
        return cls(path, key)

    def __init__(self, path, key):
        self.path, self.key = Path(path), key
        _private_file(self.path)
        with closing(self.connect()) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != {'meta','mailboxes','messages','deliveries'}:
                raise SensorBlocked('sensor_schema_invalid')
            rows = conn.execute('SELECT version,key_check,cutoff FROM meta').fetchall()
            if len(rows) != 1 or rows[0][0] != 1:
                raise SensorBlocked('sensor_schema_invalid')
            if not hmac.compare_digest(rows[0][1], fingerprint(key, 'sensor-key-check-v1')):
                raise SensorBlocked('sensor_history_key_mismatch')
            if conn.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise SensorBlocked('sensor_integrity_failed')
            self.cutoff = rows[0][2]

    def connect(self):
        _private_file(self.path)
        # rw refuses disappearance instead of creating a blank replacement.
        conn = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=5)
        conn.execute('PRAGMA synchronous=FULL')
        return conn

    def register(self, mailbox):
        with closing(self.connect()) as conn:
            conn.execute('INSERT OR IGNORE INTO mailboxes(mailbox,epoch,last_uid) VALUES (?,0,0)', (mailbox,))
            conn.commit()

    def blocked(self, mailbox):
        with closing(self.connect()) as conn:
            return bool(conn.execute('SELECT blocked FROM mailboxes WHERE mailbox=?', (mailbox,)).fetchone()[0])

    def block(self, mailbox):
        with closing(self.connect()) as conn:
            conn.execute('UPDATE mailboxes SET blocked=1 WHERE mailbox=?', (mailbox,))
            conn.commit()

    def unresolved_candidate_count(self, mailbox):
        """Count durable consumed or oversized observations, without actor authority."""
        with closing(self.connect()) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM messages WHERE mailbox=? AND outcome='BLOCKED'",
                (mailbox,),
            ).fetchone()[0]

    def attach(self, mailbox, epoch):
        epoch = positive_uid(str(epoch))
        with closing(self.connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT OR IGNORE INTO mailboxes(mailbox,epoch,last_uid) VALUES (?,?,0)',
                         (mailbox, epoch))
            stored, uid = conn.execute('SELECT epoch,last_uid FROM mailboxes WHERE mailbox=?', (mailbox,)).fetchone()
            if stored == 0:
                conn.execute('UPDATE mailboxes SET epoch=? WHERE mailbox=?', (epoch,mailbox))
            elif stored != epoch:
                raise SensorBlocked('uidvalidity_changed_manual_reconciliation_required')
            conn.commit()
            return uid

    def record(self, mailbox, epoch, uid, message, outcome):
        if outcome not in {'IGNORED','WARNING','BLOCKED'}:
            raise SensorBlocked('sensor_outcome_invalid')
        uid = positive_uid(str(uid))
        with closing(self.connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT epoch,last_uid FROM mailboxes WHERE mailbox=?', (mailbox,)).fetchone()
            if row is None or row[0] != epoch:
                raise SensorBlocked('sensor_epoch_mismatch')
            old = conn.execute('SELECT message FROM deliveries WHERE mailbox=? AND epoch=? AND uid=?',
                               (mailbox,epoch,uid)).fetchone()
            if old and old[0] != message:
                raise SensorBlocked('immutable_uid_content_changed')
            if uid <= row[1]:
                return False
            new = conn.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?)',
                               (mailbox,message,outcome)).rowcount == 1
            conn.execute('INSERT INTO deliveries VALUES (?,?,?,?)', (mailbox,epoch,uid,message))
            conn.execute('UPDATE mailboxes SET last_uid=? WHERE mailbox=?', (uid,mailbox))
            conn.commit()
            return new

    def verify_backup(self):
        """Local backup/reopen only; no off-host or Windows restart claim."""
        with tempfile.TemporaryDirectory(prefix='.sensor-check-', dir=self.path.parent) as temp:
            backup = Path(temp) / 'sensor.sqlite'
            fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
            with closing(self.connect()) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target)
            restored = SensorStore(backup, self.key)
            with closing(restored.connect()) as conn:
                return conn.execute('PRAGMA quick_check').fetchall() == [('ok',)]

    def due(self, mailbox):
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT due FROM mailboxes WHERE mailbox=?', (mailbox,)).fetchone()
            return row[0] if row else 0

    def schedule(self, mailbox, now, *, failed=False):
        with closing(self.connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT failures FROM mailboxes WHERE mailbox=?', (mailbox,)).fetchone()
            if row is None:
                raise SensorBlocked('mailbox_not_registered')
            count = min(row[0] + 1, 10) if failed else 0
            delay = min(900, 60 * 2 ** max(0, count - 1)) if failed else 60
            conn.execute('UPDATE mailboxes SET failures=?,due=? WHERE mailbox=?', (count,now+delay,mailbox))
            conn.commit()
            return delay
