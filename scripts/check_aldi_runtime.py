#!/usr/bin/env python3
"""Inspect the existing private journal and verify a local backup/restore.

No provider access, credential loading, journal initialization or mutation of
production rows. Temporary private backup bytes stay on the journal filesystem
and are removed on exit; only fixed booleans and aggregate counts are reported.
"""
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile


def inspect_runtime(raw_path):
    path = Path(raw_path)
    if os.name != 'posix':
        raise RuntimeError('private_posix_journal_required')
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError('persistent_journal_unavailable')
    if any(parent.is_symlink() for parent in path.parents):
        raise RuntimeError('journal_parent_symlink_rejected')
    if path.stat().st_mode & 0o777 != 0o600 or path.parent.stat().st_mode & 0o022:
        raise RuntimeError('private_journal_permissions_required')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        workspace = os.environ.get('GITHUB_WORKSPACE')
        if (os.environ.get('RUNNER_ENVIRONMENT') != 'self-hosted' or not workspace
                or path.resolve().is_relative_to(Path(workspace).resolve())):
            raise RuntimeError('durable_runner_required')

    def validate(connection):
        if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise RuntimeError('journal_integrity_failed')
        connection.execute('SELECT recharge_id, provider, username, status, '
                           'created_at, updated_at FROM recharges LIMIT 0')
        rows = connection.execute('SELECT status, COUNT(*) FROM recharges GROUP BY status').fetchall()
        if any(status not in {'PENDING', 'UNKNOWN', 'SUCCESS', 'FAILED'} for status, _ in rows):
            raise RuntimeError('journal_status_invalid')
        return dict(rows)

    # mode=ro refuses a missing source and cannot create or normalize it.
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        counts = validate(source)
        with tempfile.TemporaryDirectory(prefix='.aldi-journal-check-', dir=path.parent) as temp:
            backup = Path(temp) / 'backup.sqlite'
            fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
            with backup.open('rb') as stream:
                os.fsync(stream.fileno())
            with closing(sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)) as restored:
                if validate(restored) != counts:
                    raise RuntimeError('journal_changed_during_probe')
    return {
        'status': 'BLOCKED', 'journal_present': True, 'private_permissions_verified': True,
        'schema_and_integrity_verified': True, 'local_backup_restore_verified': True,
        'pending': counts.get('PENDING', 0), 'unknown': counts.get('UNKNOWN', 0),
        'host_restart_persistence_verified': False, 'off_host_backup_verified': False,
        'account_binding_verified': False, 'provider_action': False, 'booking_enabled': False,
    }


def main():
    try:
        report = inspect_runtime(os.environ.get('ALDI_JOURNAL_PATH', ''))
    except Exception:
        # Never emit arbitrary exception messages, private paths or row data.
        print(json.dumps({'status': 'BLOCKED', 'runtime_probe_completed': False,
                          'error': 'private_runtime_unverified', 'provider_action': False,
                          'booking_enabled': False}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 2 if report['pending'] or report['unknown'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
