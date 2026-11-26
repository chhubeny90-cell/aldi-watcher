"""Offline-only copied integration harness for ALDI and LIDL.

This intentionally does NOT import either live provider driver and cannot
read secrets, access a browser, make network requests or place bookings.
"""
from dataclasses import dataclass

from core.idle_scheduler import Decision, decide


@dataclass(frozen=True)
class RecordedSignal:
    provider: str
    now: int
    last_measured_activity: int | None
    last_check: int
    consumed_mail: bool = False
    unresolved_booking: bool = False


def replay(signal: RecordedSignal) -> Decision:
    if signal.provider not in {"ALDI", "LIDL"}:
        raise ValueError("unsupported_provider")
    return decide(
        now=signal.now,
        last_measured_activity=signal.last_measured_activity,
        last_check=signal.last_check,
        consumed_mail=signal.consumed_mail,
        unresolved_booking=signal.unresolved_booking,
    )
