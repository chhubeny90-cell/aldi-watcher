"""Offline contract: mailbox text is a hint, not a provider authorization."""
from datetime import datetime, timezone

import pytest

from core.dual_monitor_bridge import advisory_from_mail_report


NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


def base(mailboxes):
    return {
        "sensor_only": True,
        "provider_action": False,
        "booking_enabled": False,
        "mailboxes": mailboxes,
    }


def test_standby_keeps_mail_sensor_without_provider_calls():
    hint = advisory_from_mail_report(base([{"state": "IDLE"}]), now=NOW)
    assert hint["state"] == "STANDBY"
    assert hint["mail_poll_seconds"] == 60
    assert hint["account_poll_seconds"] is None
    assert hint["account_read_due_now"] is False
    assert hint["booking_authorized"] is False


@pytest.mark.parametrize("mailbox", [
    {"state": "BLOCKED", "blocked_candidates": 1},
    {"state": "IDLE", "warnings": 1},
    {"state": "BLOCKED", "unresolved_candidates": 1},
])
def test_mail_candidate_requires_verification_not_automatic_login(mailbox):
    hint = advisory_from_mail_report(base([mailbox]), now=NOW)
    assert hint["state"] == "VERIFICATION_REQUIRED"
    assert hint["unverified_mail_candidate"] is True
    assert hint["next_step"] == "verify_mail_and_target_sim"
    assert hint["account_read_due_now"] is False
    assert hint["booking_authorized"] is False


def test_transient_imap_problem_does_not_wake_provider():
    hint = advisory_from_mail_report(base([{"state": "RETRY_WAIT"}]), now=NOW)
    assert hint["state"] == "SENSOR_ERROR"
    assert hint["next_step"] == "sensor_diagnostic"
    assert hint["account_read_due_now"] is False


@pytest.mark.parametrize("bad", [
    {"sensor_only": False, "provider_action": False, "booking_enabled": False, "mailboxes": []},
    {"sensor_only": True, "provider_action": True, "booking_enabled": False, "mailboxes": []},
    {"sensor_only": True, "provider_action": False, "booking_enabled": True, "mailboxes": []},
    base([{"warnings": -1}]),
    base([{"blocked_candidates": True}]),
    base(None),
])
def test_malformed_or_actionable_reports_fail_closed(bad):
    with pytest.raises(ValueError):
        advisory_from_mail_report(bad, now=NOW)
