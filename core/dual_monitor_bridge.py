"""Untrusted mail sensor -> dual-monitor advisory (strictly read-only).

The IMAP sensor only recognizes message wording. It does not yet prove sender
authenticity, target SIM, eligible tariff, or the state of an ALDI account.
A candidate therefore creates an advisory for further verification, never a
provider login, account polling request or booking.
"""
from datetime import datetime
from core.dual_monitor_policy import schedule_dual_monitor


def advisory_from_mail_report(report: dict, *, now: datetime) -> dict:
    """Attach a safe monitoring hint to one completed IMAP cycle.

    The future authenticated ALDI read-only worker may consume a separate,
    approved event contract, but must NOT interpret this advisory as permission
    to log in, query the provider, or click a booking control.
    """
    if (report.get("sensor_only") is not True
            or report.get("provider_action") is not False
            or report.get("booking_enabled") is not False):
        raise ValueError("unverified_sensor_report")
    mailboxes = report.get("mailboxes")
    if not isinstance(mailboxes, list):
        raise ValueError("invalid_mailbox_report")
    for mailbox in mailboxes:
        if not isinstance(mailbox, dict):
            raise ValueError("invalid_mailbox_report")
        for counter in ("warnings", "blocked_candidates", "unresolved_candidates"):
            value = mailbox.get(counter, 0)
            if type(value) is not int or value < 0:
                raise ValueError("invalid_mailbox_counter")

    candidate_pending = any(
        mb.get("blocked_candidates", 0) or mb.get("unresolved_candidates", 0)
        for mb in mailboxes
    )
    warning_seen = any(mb.get("warnings", 0) > 0 for mb in mailboxes)
    sensor_error = any(
        mb.get("state") in ("BLOCKED", "RETRY_WAIT") for mb in mailboxes
    )

    # No input here qualifies as a verified mail signal. The underlying
    # policy is evaluated in safe idle mode; do not feed untrusted mail to it.
    baseline = schedule_dual_monitor(now=now, mail_signal="none")
    return {
        "state": "VERIFICATION_REQUIRED" if candidate_pending or warning_seen
                 else "SENSOR_ERROR" if sensor_error else baseline.state,
        "mail_poll_seconds": baseline.mail_poll_seconds,
        "account_poll_seconds": None,
        "account_read_due_now": False,
        "booking_authorized": False,
        "unverified_mail_candidate": bool(candidate_pending or warning_seen),
        "next_step": "verify_mail_and_target_sim" if candidate_pending or warning_seen
                     else "sensor_diagnostic" if sensor_error else "wait_for_signal",
    }
