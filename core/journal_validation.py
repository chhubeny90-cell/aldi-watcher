"""Read-only journal checks shared by the runtime probe and live actor."""
from contextlib import closing
import os
import re
import sqlite3


RECHARGES_TABLE_SQL = """CREATE TABLE recharges (
    recharge_id TEXT PRIMARY KEY NOT NULL,
    provider TEXT NOT NULL,
    username TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING','UNKNOWN','SUCCESS','FAILED')),
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""


def _schema_tokens(sql):
    """Accept only the canonical table grammar, never substring/sentinel proofs.

    Consume the complete SQL. Comments/spacing do not matter; string literals
    remain case-sensitive. Extra CHECK alternatives, collations, expressions or
    constraints are rejected, even if a few behavioral probes would pass.
    """
    if not isinstance(sql, str) or len(sql) > 65536:
        raise RuntimeError('journal_schema_invalid')
    token = re.compile(
        r"(?P<space>\s+)|(?P<comment>--[^\n]*(?:\n|$)|/\*.*?\*/)|"
        r"(?P<string>'(?:[^']|'')*')|(?P<word>[A-Za-z_][A-Za-z_0-9]*)|"
        r'(?P<quoted>"(?:[^"]|"")*"|`[^`]*`|\[[^\]]*\])|(?P<symbol>[(),;])',
        re.S,
    )
    result, pos = [], 0
    while pos < len(sql):
        match = token.match(sql, pos)
        if match is None:
            raise RuntimeError('journal_schema_invalid')
        pos = match.end()
        kind, value = match.lastgroup, match.group()
        if kind in {'space', 'comment'}:
            continue
        if kind == 'word': value = value.lower()
        elif kind == 'quoted': value = value[1:-1].replace('""', '"').lower()
        result.append(value)
    if result[-1:] == [';']: result.pop()
    if result[:5] == ['create', 'table', 'if', 'not', 'exists']:
        del result[2:5]
    return result


def validate_journal(connection):
    if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise RuntimeError('journal_integrity_failed')
    connection.execute('SELECT recharge_id, provider, username, status, '
                       'created_at, updated_at FROM recharges LIMIT 0')
    # Fail closed on partial lookalike tables; the actor requires all seven
    # columns and integrity constraints, not just a readable SELECT.
    cols = connection.execute("PRAGMA table_info('recharges')").fetchall()
    expected = [
        ('recharge_id', 'TEXT', 1, 1),
        ('provider', 'TEXT', 1, 0),
        ('username', 'TEXT', 1, 0),
        ('status', 'TEXT', 1, 0),
        ('error_message', 'TEXT', 0, 0),
        ('created_at', 'TEXT', 1, 0),
        ('updated_at', 'TEXT', 1, 0),
    ]
    if [(c[1], c[2].upper(), c[3], c[5]) for c in cols] != expected:
        raise RuntimeError('journal_schema_invalid')
    schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='recharges'"
    ).fetchone()
    if schema is None or _schema_tokens(schema[0]) != _schema_tokens(RECHARGES_TABLE_SQL):
        raise RuntimeError('journal_schema_invalid')
    # Triggers could delete/rewrite a successfully inserted reservation. Unknown
    # behavior on the actor's safety table is never accepted as durable storage.
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='recharges'"
    ).fetchone():
        raise RuntimeError('journal_schema_invalid')
    # Verify the actual SQLite constraint behavior on an in-memory backup.
    # Text matching sqlite_master can be fooled by comments or string literals.
    with closing(sqlite3.connect(':memory:')) as probe:
        connection.backup(probe)
        probe.execute('SAVEPOINT aldi_status_schema_probe')
        try:
            def insert_probe(status):
                probe.execute(
                    'INSERT INTO recharges '
                    '(recharge_id, provider, username, status, error_message, created_at, updated_at) '
                    'VALUES (?, ?, ?, ?, NULL, ?, ?)',
                    ('schema-probe-' + os.urandom(12).hex(), 'aldi_talk',
                     'schema-probe-' + os.urandom(12).hex(), status,
                     '2000-01-01T00:00:00Z', '2000-01-01T00:00:00Z'),
                )
            for status in ('PENDING', 'UNKNOWN', 'SUCCESS', 'FAILED'):
                try:
                    insert_probe(status)
                except sqlite3.Error:
                    raise RuntimeError('journal_schema_invalid') from None
                probe.execute('ROLLBACK TO aldi_status_schema_probe')
            try:
                insert_probe('BOGUS')
            except sqlite3.IntegrityError:
                pass
            except sqlite3.Error:
                raise RuntimeError('journal_schema_invalid') from None
            else:
                raise RuntimeError('journal_schema_invalid')
        finally:
            probe.execute('ROLLBACK TO aldi_status_schema_probe')
            probe.execute('RELEASE aldi_status_schema_probe')
    indexes = connection.execute("PRAGMA index_list('recharges')").fetchall()
    if not any(
        i[4] == 0 and
        [c[2] for c in connection.execute('SELECT * FROM pragma_index_info(?)', (i[1],))]
        == ['provider', 'username', 'status', 'created_at'] for i in indexes
    ):
        raise RuntimeError('journal_schema_invalid')
    rows = connection.execute('SELECT status, COUNT(*) FROM recharges GROUP BY status').fetchall()
    if any(status not in {'PENDING', 'UNKNOWN', 'SUCCESS', 'FAILED'} for status, _ in rows):
        raise RuntimeError('journal_status_invalid')
    return dict(rows)

