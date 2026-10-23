#!/usr/bin/env python3
"""Create or validate the private durable SQLite journal used by live ALDI refills.

This command never reads provider credentials and never contacts ALDI. It only
initializes the local journal path supplied by the operator.
"""

import argparse
from contextlib import closing
import json
import os
import sqlite3
import sys
from pathlib import Path

# Make the documented direct invocation (`python scripts/...`) resolve project
# modules exactly like the workflow/tests do from the repository checkout.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.database import Database
from core.journal_validation import validate_journal


def initialize_journal(raw_path: str):
    if os.name != "posix":
        raise RuntimeError("posix_required")

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise RuntimeError("absolute_path_required")
    if path.is_symlink():
        raise RuntimeError("journal_symlink_rejected")
    if not path.parent.is_dir():
        raise RuntimeError("journal_parent_missing")
    if any(parent.is_symlink() for parent in path.parents):
        raise RuntimeError("journal_parent_symlink_rejected")
    # A group/world-writable parent lets another local process replace the file
    # between checks even when the SQLite file itself is mode 0600.
    if path.parent.stat().st_mode & 0o022:
        raise RuntimeError("journal_parent_must_not_be_group_or_world_writable")

    existed = path.exists()
    if existed:
        if not path.is_file():
            raise RuntimeError("journal_not_regular_file")
        # Validate an existing runtime file before Database can normalize modes.
        # Deployment mistakes must be visible instead of silently repaired.
        if path.stat().st_mode & 0o777 != 0o600:
            raise RuntimeError("journal_permissions_must_be_0600")
        # Existing history is inspected read-only before any constructor can
        # normalize it. Legacy schemas require an explicit offline migration.
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
            validate_journal(conn)

    # Database creates a missing file with 0600 and initializes the schema.
    db = Database(str(path))
    del db

    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise RuntimeError("journal_permissions_must_be_0600")

    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
        validate_journal(conn)

    return {
        "journal_ready": True,
        "created": not existed,
        "permissions": "0600",
        "schema_verified": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Absolute local path for the durable SQLite journal")
    args = parser.parse_args(argv)
    result = initialize_journal(args.path)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
