"""GitHub-hosted entry point for the guarded ALDI live-refill runner.

The hosted adapter keeps provider-changing actions behind durable remote guards,
adds one-shot manual auth override, maintenance-aware backoff, target-account
verification, crash recovery proofs, usage-mail dedupe and heartbeat updates.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

import aldi_live_refill as live
import watcher
from core.aldi_http_login import LoginError, phone_identifier
from core.database import Database
from github_journal_state import (
    auth_backoff_active,
    restore_journal,
    set_auth_backoff,
    sync_journal,
)
from github_hardening_state import (
    claim_trigger_key,
    clear_auth_backoff,
    clear_recovery_proof,
    set_recovery_proof,
    touch_heartbeat,
)


_ORIGINAL_BEGIN = Database.begin_recharge
_ORIGINAL_SET = Database.set_recharge_status
_ORIGINAL_BOUND_STATUS = live._bound_status
_ORIGINAL_LOGIN = watcher.aldi_login
_ORIGINAL_LOGIN_FAILURE = live._login_failure_outcome
_CURRENT_BASELINE = None


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


def _tracking_bound_status(driver, account):
    global _CURRENT_BASELINE
    result = _ORIGINAL_BOUND_STATUS(driver, account)
    _CURRENT_BASELINE = result
    return result


def _syncing_begin(self, *args, **kwargs):
    # begin_recharge commits PENDING locally. Do not return to the caller (which
    # may click the provider control) until the unresolved guard is durable.
    recharge_id = _ORIGINAL_BEGIN(self, *args, **kwargs)
    sync_journal(self.db_path)
    if _CURRENT_BASELINE is not None:
        before, binding = _CURRENT_BASELINE
        # This second CAS-protected state write is still before the click. It
        # stores HMAC proofs only, never the allowance or account identity.
        set_recovery_proof(recharge_id, before, binding)
    return recharge_id


def _syncing_set(self, *args, **kwargs):
    status = _ORIGINAL_SET(self, *args, **kwargs)
    sync_journal(self.db_path)
    recharge_id = args[0] if args else kwargs.get("recharge_id")
    if status in {"SUCCESS", "FAILED"} and recharge_id:
        try:
            clear_recovery_proof(recharge_id)
        except Exception:
            # A stale proof is non-authoritative and contains no plaintext data.
            pass
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


def _write_simple_report(outcome, **extra):
    now = datetime.now(timezone.utc).isoformat()
    report = {
        "started_at": now,
        "finished_at": now,
        "outcome": outcome,
        "booking_enabled": True,
        "booking_clicks": 0,
        "confirmation_clicks": 0,
        "successful_refills": 0,
        "cycles": [],
    }
    report.update(extra)
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


def _write_backoff_report():
    _write_simple_report("auth_backoff_active")


def _report_outcome():
    path = _report_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    outcome = payload.get("outcome") if isinstance(payload, dict) else None
    return outcome if isinstance(outcome, str) else None


def _manual_auth_once():
    return os.environ.get("ALDI_MANUAL_AUTH_ONCE", "").strip().lower() == "true"


def _target_guard():
    expected = os.environ.get("ALDI_EXPECTED_ACCOUNT", "").strip()
    if not expected:
        return None
    if not watcher.configure_credentials("ALDI"):
        return "credentials_unavailable"
    try:
        actual = phone_identifier(watcher.ALDI_ACCOUNT_USER)
        wanted = phone_identifier(expected)
    except LoginError:
        return "target_account_guard_invalid"
    return None if actual == wanted else "target_account_mismatch"


def _provider_login_outcome(driver):
    try:
        provider = live.diagnostics(driver).get("provider_indications") or {}
    except Exception:
        return "auth_failed"
    if provider.get("maintenance") is True:
        return "provider_maintenance"
    if provider.get("account_locked") is True:
        return "account_locked"
    return "auth_failed"


def _maintenance_aware_login(driver):
    try:
        return _ORIGINAL_LOGIN(driver)
    except Exception:
        if _provider_login_outcome(driver) == "provider_maintenance":
            # Let live.main() use its ordinary false-login branch so the fixed
            # maintenance outcome is preserved instead of becoming generic error.
            return False
        raise


def _recover_recharge_status(driver, recharge_id):
    """Keep old operations blocked until an official completion lookup exists.

    A stored baseline and matching account do not bind a later allowance
    increase to this operation. Do not release its reservation from volume,
    even when the HMAC-protected recovery baseline is available.
    """
    return "UNKNOWN"


def _claim_mail_trigger():
    message_key = os.environ.get("ALDI_TRIGGER_MESSAGE_KEY", "").strip()
    if not message_key:
        return True
    if os.environ.get("ALDI_TRIGGER_PRECLAIMED", "").strip().lower() == "true":
        # A caller-provided flag is not proof of a durable reservation.
        # Reject until the mail handoff is bound to the authoritative journal.
        raise RuntimeError("unverified_mail_handoff_blocked")
    return claim_trigger_key(message_key)


def _heartbeat():
    try:
        touch_heartbeat()
    except Exception:
        pass
    url = os.environ.get("WATCHER_HEARTBEAT_URL", "").strip()
    if not url:
        return
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return
    try:
        requests.get(url, timeout=10, allow_redirects=False)
    except requests.RequestException:
        pass


def _main():
    global _CURRENT_BASELINE
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("github_actions_required")
    if os.environ.get("ALDI_REMOTE_JOURNAL", "").lower() != "true":
        raise RuntimeError("remote_journal_not_enabled")

    _journal_path()

    if not _claim_mail_trigger():
        _write_simple_report("duplicate_trigger")
        return 0

    manual_once = _manual_auth_once()
    if auth_backoff_active() and not manual_once:
        _write_backoff_report()
        return 0

    target_outcome = _target_guard()
    if target_outcome is not None:
        _write_simple_report(target_outcome)
        return 2 if target_outcome != "credentials_unavailable" else 3

    previous_begin = Database.begin_recharge
    previous_set = Database.set_recharge_status
    previous_open = live.open_live_journal
    previous_bound = live._bound_status
    previous_recover = live.check_recharge_status
    previous_login_failure = live._login_failure_outcome
    previous_login = watcher.aldi_login
    _CURRENT_BASELINE = None
    try:
        Database.begin_recharge = _syncing_begin
        Database.set_recharge_status = _syncing_set
        live.open_live_journal = _open_cloud_journal
        live._bound_status = _tracking_bound_status
        live.check_recharge_status = _recover_recharge_status
        live._login_failure_outcome = _provider_login_outcome
        watcher.aldi_login = _maintenance_aware_login
        result = live.main()
    finally:
        Database.begin_recharge = previous_begin
        Database.set_recharge_status = previous_set
        live.open_live_journal = previous_open
        live._bound_status = previous_bound
        live.check_recharge_status = previous_recover
        live._login_failure_outcome = previous_login_failure
        watcher.aldi_login = previous_login
        _CURRENT_BASELINE = None

    outcome = _report_outcome()
    if outcome == "account_locked":
        set_auth_backoff(hours=24)
    elif outcome == "provider_maintenance":
        set_auth_backoff(hours=0.5)
    elif outcome == "auth_failed":
        set_auth_backoff(hours=1)
    elif outcome in {
        "not_needed", "free_refill_unavailable", "refill_verified",
        "run_limit_reached", "recovery_complete", "unresolved_recharge_blocked",
        "unknown_after_click", "booking_control_unverified",
        "identity_changed_before_click", "offer_changed_before_click",
    }:
        try:
            clear_auth_backoff()
        except Exception:
            pass
    return result


def main():
    try:
        return _main()
    finally:
        _heartbeat()


if __name__ == "__main__":
    raise SystemExit(main())
