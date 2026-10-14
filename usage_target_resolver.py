"""Resolve an ALDI usage-mail wake-up to exactly one monitored account.

This module performs no provider login and no booking. It consumes sanitized
reports produced by the usage-mail monitor and the read-only multi-account
monitor. A target is resolved only when exactly one enabled free-unlimited
profile is both below 1 GB and explicitly eligible for the free 1-GB refill.

The resolver emits only account_id, never a phone number or credential. Live
handoff remains disabled here; a caller must apply its own explicit provider
authorization and booking gate after target resolution.
"""

import json
import math
import os
from pathlib import Path


MAIL_REPORT = os.getenv("ALDI_MAIL_NOTIFY_REPORT", "aldi-usage-alert.json")
ACCOUNTS_REPORT = os.getenv("ALDI_ACCOUNTS_REPORT", "aldi-accounts-report.json")
ROUTE_REPORT = os.getenv("ALDI_USAGE_ROUTE_REPORT", "aldi-usage-route.json")


def _valid_remaining(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def _signals(mail_report):
    alerts = mail_report.get("alerts") or []
    return sorted({
        str(item.get("signal"))
        for item in alerts
        if isinstance(item, dict) and item.get("signal") in {"80_percent", "consumed"}
    })


def _candidate(account):
    if not isinstance(account, dict):
        return False
    remaining = account.get("inland_frei_gb")
    return (
        account.get("status") == "ok"
        and account.get("requested_policy") == "free_unlimited"
        and account.get("booking_executed") is False
        and _valid_remaining(remaining)
        and float(remaining) < 1.0
        and account.get("refill_eligible") is True
        and isinstance(account.get("account_id"), str)
        and bool(account.get("account_id"))
    )


def resolve(mail_report, accounts_report):
    """Return a sanitized, fail-closed routing decision."""
    signals = _signals(mail_report if isinstance(mail_report, dict) else {})
    new_alerts = mail_report.get("new_alerts") if isinstance(mail_report, dict) else None
    if not isinstance(new_alerts, int) or new_alerts <= 0 or not signals:
        return {
            "status": "no_usage_signal",
            "signals": signals,
            "candidate_count": 0,
            "target_account_id": None,
            "handoff_allowed": False,
        }

    accounts = accounts_report.get("accounts") if isinstance(accounts_report, dict) else None
    if not isinstance(accounts, list):
        return {
            "status": "account_report_unavailable",
            "signals": signals,
            "candidate_count": 0,
            "target_account_id": None,
            "handoff_allowed": False,
        }

    candidates = [item for item in accounts if _candidate(item)]
    if len(candidates) == 1:
        return {
            "status": "target_resolved",
            "signals": signals,
            "candidate_count": 1,
            "target_account_id": candidates[0]["account_id"],
            "handoff_allowed": False,
        }
    return {
        "status": "target_ambiguous" if len(candidates) > 1 else "target_not_found",
        "signals": signals,
        "candidate_count": len(candidates),
        "target_account_id": None,
        "handoff_allowed": False,
    }


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, payload):
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def main():
    try:
        mail_report = _read(MAIL_REPORT)
    except (OSError, json.JSONDecodeError):
        mail_report = {}
    try:
        accounts_report = _read(ACCOUNTS_REPORT)
    except (OSError, json.JSONDecodeError):
        accounts_report = {}

    decision = resolve(mail_report, accounts_report)
    _write(ROUTE_REPORT, decision)
    print(json.dumps(decision, ensure_ascii=False), flush=True)
    return 0 if decision["status"] in {"no_usage_signal", "target_resolved"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
