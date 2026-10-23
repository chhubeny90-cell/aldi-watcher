"""One manually cleared, durably reserved login; no booking or retry."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.aldi_http_login import AldiHttpLogin, LoginError, phone_identifier
from core.credentials import get_credential
from github_journal_state import consistent_mail_snapshot, _put_state


def _credentials():
    """Reject reruns, unconfirmed recovery and an ambiguous SIM before any I/O."""
    if (os.environ.get("GITHUB_REPOSITORY") != "chhubeny90-cell/aldi-watcher"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"
            or not re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", ""))
            or not re.fullmatch(r"[1-9][0-9]*", os.environ.get("GITHUB_RUN_ID", ""))):
        raise LoginError("controlled_dispatch_required")
    if os.environ.get("AUTO_BOOK_ENABLED") != "false":
        raise LoginError("read_only_required")
    if os.environ.get("ALDI_MANUAL_LOGIN_VERIFIED") != "true":
        raise LoginError("manual_login_verification_required")
    expected = os.environ.get("ALDI_EXPECTED_ACCOUNT")
    if not expected:
        raise LoginError("expected_account_required")
    expected = phone_identifier(expected)
    phone = phone_identifier(get_credential("ALDI_USER"))
    if phone != expected:
        raise LoginError("configured_account_mismatch")
    password = get_credential("ALDI_PASS")
    if not password:
        raise LoginError("password_missing")
    return expected, password


def _reserve_attempt(now, report):
    """CAS a 24-hour guard BEFORE provider I/O, including crash/timeout cases.

    Existing state must be readable and coherent. Never create replacement
    history, clear a backoff, or retry a conflicted/uncertain reservation.
    """
    _, events, journal = consistent_mail_snapshot()
    if journal is None:
        raise LoginError("auth_guard_missing")
    sha, state = journal
    if state["unresolved"] or any(
            event["phase"] in {"IN_FLIGHT", "QUARANTINED_UNKNOWN"}
            for event in events.values()):
        raise LoginError("unresolved_provider_state")
    retry_text = state["auth_retry_after"]
    if retry_text is not None:
        retry = datetime.fromisoformat(retry_text.replace("Z", "+00:00"))
        if now < retry:
            raise LoginError("auth_backoff_active")
    reserved = dict(state, auth_retry_after=(now + timedelta(hours=24))
                    .astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
    report["reservation_status"] = "unconfirmed"
    _put_state(reserved, sha, message="Reserve one controlled read-only ALDI login")
    _, current_events, current_journal = consistent_mail_snapshot()
    if (current_journal is None or current_journal[1] != reserved
            or current_events != events):
        raise LoginError("auth_reservation_unverified")
    report["reservation_status"] = "confirmed"


def main():
    client = None
    report = {"login_ok": False, "account_match": False,
              "credential_submissions": 0, "phase": "preflight",
              "started_at": datetime.now(timezone.utc).isoformat(),
              "booking_clicks": 0, "read_only": True,
              "reservation_status": "not_attempted", "tariff_loaded": False,
              "remaining_volume_loaded": False}
    try:
        phone, password = _credentials()
        report["commit"] = os.environ["GITHUB_SHA"]
        report["run_id"] = os.environ["GITHUB_RUN_ID"]
        report["phase"] = "reserve_attempt"
        _reserve_attempt(datetime.now(timezone.utc), report)
        client = AldiHttpLogin()
        client.report.update(report)
        report = client.report
        client.login(phone, password)
        report["outcome"] = "login_verified"
        return 0
    except LoginError as exc:
        report["outcome"] = str(exc)
        return 2
    except Exception as exc:
        report["outcome"] = "probe_error"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        path = Path(os.getenv("ALDI_HTTP_REPORT", "aldi-http-login.json"))
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
