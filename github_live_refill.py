"""GitHub-hosted entry point for the guarded ALDI live-refill runner.

GitHub-hosted runners are ephemeral. This adapter rehydrates only unresolved
operation guards after the configured account is known, then persists each
PENDING/UNKNOWN transition remotely without writing the account identity.
"""

import os
from pathlib import Path

import aldi_live_refill as live
import watcher
from core.database import Database
from github_journal_state import restore_journal, sync_journal


_ORIGINAL_BEGIN = Database.begin_recharge
_ORIGINAL_SET = Database.set_recharge_status


def _journal_path():
    path = Path(os.environ.get("ALDI_JOURNAL_PATH", ""))
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("cloud_journal_path_invalid")
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        workspace_path = Path(workspace).resolve()
        try:
            path.resolve().relative_to(workspace_path)
        except ValueError:
            pass
        else:
            raise RuntimeError("cloud_journal_must_be_outside_workspace")
    return path


def _syncing_begin(self, *args, **kwargs):
    # begin_recharge commits PENDING locally. Do not return to the caller (which
    # may click the provider control) until that unresolved guard is durable.
    recharge_id = _ORIGINAL_BEGIN(self, *args, **kwargs)
    sync_journal(self.db_path)
    return recharge_id


def _syncing_set(self, *args, **kwargs):
    status = _ORIGINAL_SET(self, *args, **kwargs)
    sync_journal(self.db_path)
    return status


def _open_cloud_journal():
    path = _journal_path()
    # live.main() configures credentials before opening the journal, so the
    # account is available here but is never included in remote state.
    restore_journal(path, watcher.ALDI_ACCOUNT_USER)
    if not path.is_file():
        raise RuntimeError("cloud_journal_unavailable")
    if os.name != "posix" or path.stat().st_mode & 0o077:
        raise RuntimeError("private_posix_journal_required")
    return Database(str(path))


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("github_actions_required")
    if os.environ.get("ALDI_REMOTE_JOURNAL", "").lower() != "true":
        raise RuntimeError("remote_journal_not_enabled")

    _journal_path()
    Database.begin_recharge = _syncing_begin
    Database.set_recharge_status = _syncing_set
    live.open_live_journal = _open_cloud_journal
    return live.main()


if __name__ == "__main__":
    raise SystemExit(main())
