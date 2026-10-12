"""GitHub-hosted entry point for the guarded ALDI live-refill runner.

GitHub-hosted runners are ephemeral. This adapter rehydrates only unresolved
operation guards after the configured account is known, persists each
PENDING/UNKNOWN transition remotely without writing the account identity, and
backs off repeated credential submissions after authentication failures.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aldi_live_refill as live
import watcher
from core.database import Database
from github_journal_state import (
    auth_backoff_active,
    restore_journal,
    set_auth_backoff,
    sync_journal,
)


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


def _report_path():
    return Path(os.environ.get("ALDI_LIVE_REPORT", "aldi-live-refill.json"))


def _write_backoff_report():
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "started_at": now,
        "finished_at": now,
        "outcome": "auth_backoff_active",
        "booking_enabled": True,
        "booking_clicks": 0,
        "confirmation_clicks": 0,
        "successful_refills": 0,
        "cycles": [],
    }
    path = _report_path()
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    print(json.dumps({
        "outcome": report["outcome"],
        "booking_enabled": True,
        "booking_clicks": 0,
        "confirmation_clicks": 0,
        "successful_refills": 0,
    }), flush=True)


def _report_outcome():
    path = _report_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    outcome = payload.get("outcome") if isinstance(payload, dict) else None
    return outcome if isinstance(outcome, str) else None


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("github_actions_required")
    if os.environ.get("ALDI_REMOTE_JOURNAL", "").lower() != "true":
        raise RuntimeError("remote_journal_not_enabled")

    _journal_path()

    # Do this before live.main() configures/submits provider credentials. Scheduled
    # runs continue every ten minutes, but a known lock never causes repeated
    # password submissions during the durable backoff window.
    if auth_backoff_active():
        _write_backoff_report()
        return 0

    previous_begin = Database.begin_recharge
    previous_set = Database.set_recharge_status
    previous_open = live.open_live_journal
    try:
        Database.begin_recharge = _syncing_begin
        Database.set_recharge_status = _syncing_set
        live.open_live_journal = _open_cloud_journal
        result = live.main()
    finally:
        # Never leak hosted persistence hooks into another watcher/test in the
        # same interpreter. The GitHub runner normally exits after one call, but
        # process-local cleanup keeps the adapter composable and test-safe.
        Database.begin_recharge = previous_begin
        Database.set_recharge_status = previous_set
        live.open_live_journal = previous_open

    # The live runner derives these fixed outcomes from cached sanitized provider
    # evidence only. Account lock gets a long backoff; an otherwise unknown auth
    # failure gets a shorter retry interval to avoid password hammering.
    outcome = _report_outcome()
    if outcome == "account_locked":
        set_auth_backoff(hours=6)
    elif outcome == "auth_failed":
        set_auth_backoff(hours=1)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
