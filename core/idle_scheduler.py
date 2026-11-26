"""Offline-only idle scheduling for ALDI and LIDL watchers.

This module never contacts providers or performs transactions.
"""
from dataclasses import dataclass
from enum import Enum

CHECK_SECONDS = 90
IDLE_SECONDS = 3600

class Mode(str, Enum):
    ACTIVE = "active"
    SLEEP = "sleep"

@dataclass(frozen=True)
class Decision:
    mode: Mode
    check_due: bool
    reason: str

def decide(*, now: int, last_measured_activity: int | None, last_check: int,
           consumed_mail: bool = False, unresolved_booking: bool = False) -> Decision:
    """Evaluate monotonic second timestamps, without provider side effects.

    An unknown activity timestamp never proves inactivity.
    Consumption mail wakes monitoring, but cannot authorize a booking.
    """
    if any(type(x) is not int or x < 0 for x in (now, last_check)):
        raise ValueError("invalid_timestamp")
    if last_check > now:
        raise ValueError("future_last_check")
    if last_measured_activity is not None and (
        type(last_measured_activity) is not int
        or last_measured_activity < 0 or last_measured_activity > now
    ):
        raise ValueError("invalid_last_activity")
    if unresolved_booking:
        return Decision(Mode.SLEEP, False, "unresolved_booking")
    if consumed_mail:
        return Decision(Mode.ACTIVE, True, "mail_wakeup")
    if last_measured_activity is not None and now - last_measured_activity >= IDLE_SECONDS:
        return Decision(Mode.SLEEP, False, "measured_idle")
    due = now - last_check >= CHECK_SECONDS
    return Decision(Mode.ACTIVE, due, "interval_due" if due else "waiting")
