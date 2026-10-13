"""Check the durable ALDI watcher heartbeat and safely request recovery.

A stale heartbeat may dispatch one guarded repository event per UTC hour. The
recovery event does not enable the manual-auth override, so provider auth
backoff, journal reservations, target-account checks and free-only booking
guards remain authoritative.
"""

import json
import os
import re
from datetime import datetime, timezone

import requests

from github_hardening_state import claim_trigger_key, heartbeat_age_seconds

RECOVERY_EVENT = "aldi-watchdog-recovery"
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _enabled():
    return os.environ.get("ALDI_WATCHDOG_RECOVERY", "false").strip().lower() == "true"


def _hourly_recovery_key(now=None):
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise RuntimeError("naive_watchdog_reference")
    hour = reference.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
    return f"watchdog-recovery:{hour}Z"


def _dispatch_recovery():
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not _REPOSITORY_RE.fullmatch(repository):
        raise RuntimeError("watchdog_repository_invalid")
    if not token:
        raise RuntimeError("watchdog_token_unavailable")
    response = requests.post(
        f"https://api.github.com/repos/{repository}/dispatches",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "event_type": RECOVERY_EVENT,
            "client_payload": {"source": "heartbeat-watchdog"},
        },
        timeout=20,
    )
    if response.status_code != 204:
        raise RuntimeError(f"watchdog_dispatch_http_{response.status_code}")


def main():
    threshold = int(os.environ.get("ALDI_HEARTBEAT_MAX_AGE_SECONDS", "1800"))
    threshold = max(300, min(86400, threshold))
    age = heartbeat_age_seconds()
    stale = age is None or age > threshold
    payload = {
        "heartbeat_present": age is not None,
        "heartbeat_age_seconds": None if age is None else round(age, 1),
        "threshold_seconds": threshold,
        "stale": stale,
        "recovery_enabled": _enabled(),
        "recovery_status": "not_needed" if not stale else "disabled",
    }

    if not stale:
        print(json.dumps(payload), flush=True)
        return 0

    if not _enabled():
        print(json.dumps(payload), flush=True)
        return 2

    try:
        claimed = claim_trigger_key(_hourly_recovery_key())
    except Exception:
        payload["recovery_status"] = "claim_failed"
        print(json.dumps(payload), flush=True)
        return 2

    if not claimed:
        payload["recovery_status"] = "already_requested_this_hour"
        print(json.dumps(payload), flush=True)
        return 2

    try:
        _dispatch_recovery()
    except Exception:
        payload["recovery_status"] = "dispatch_failed"
        print(json.dumps(payload), flush=True)
        return 2

    payload["recovery_status"] = "dispatched"
    print(json.dumps(payload), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
