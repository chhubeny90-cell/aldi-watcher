"""Read-only dual-signal scheduling for the ALDI mail and usage sensors.

Pure scheduling policy. It never opens a provider session, dispatches an
actor or authorizes a refill. The caller must authenticate/deduplicate mail,
bind every account sample to a verified SIM, and persist last_activity_at.
"""
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Iterable, Optional

from core.adaptive_monitor import UsageSample, adaptive_status


MAIL_POLL_SECONDS = 60
MIN_ACCOUNT_POLL_SECONDS = 60
ACTIVITY_WINDOW_SECONDS = 600
MAX_SAMPLE_AGE_SECONDS = 300


@dataclass(frozen=True)
class DualMonitorDecision:
    state: str
    mail_poll_seconds: int
    account_poll_seconds: Optional[int]
    account_read_due_now: bool
    booking_authorized: bool
    reason: str


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _valid_nonnegative(value: object) -> bool:
    """Reject booleans, invalid types, NaN and infinities as telemetry."""
    return type(value) in (float, int) and isfinite(value) and value >= 0


def schedule_dual_monitor(
    *,
    now: datetime,
    mail_signal: str = "none",
    network_active: bool = False,
    last_activity_at: Optional[datetime] = None,
    samples: Iterable[UsageSample] = (),
    provider_retry_after_seconds: float = 0,
) -> DualMonitorDecision:
    """Choose how often to *read* ALDI; keep the IMAP mail sensor running.

    mail_signal is a newly authenticated, deduplicated observation, not the
    unread state of a mailbox. Supported: none, 80_percent, consumed.
    network_active must come from an independent, explicit traffic monitor;
    it cannot be inferred from lack of email. A recent wake persists for ten
    minutes via the caller-provided last_activity_at.

    samples must be authenticated, read-only, and tied to the selected SIM.
    Stale readings never prove present refill eligibility. All decisions
    prohibit provider actions regardless of remaining volume.
    """
    if not _aware(now):
        raise ValueError("timezone_aware_now_required")
    if mail_signal not in ("none", "80_percent", "consumed"):
        raise ValueError("invalid_mail_signal")
    if not isinstance(network_active, bool):
        raise ValueError("network_active_must_be_boolean")
    if last_activity_at is not None:
        if not _aware(last_activity_at):
            raise ValueError("timezone_aware_activity_required")
        if last_activity_at > now:
            raise ValueError("future_activity_rejected")
    if not _valid_nonnegative(provider_retry_after_seconds):
        raise ValueError("invalid_provider_backoff")
    items = tuple(samples)
    for sample in items:
        if not isinstance(sample, UsageSample) or not _aware(sample.timestamp):
            raise ValueError("timezone_aware_samples_required")
        if sample.timestamp > now:
            raise ValueError("future_sample_rejected")
        if not _valid_nonnegative(sample.remaining_mb):
            raise ValueError("invalid_remaining_volume")
    # Conflicting volume readings for the same instant must not determine
    # an apparent 0-GB state or an invented consumption rate.
    readings_at = {}
    for sample in items:
        earlier = readings_at.setdefault(sample.timestamp, sample.remaining_mb)
        if earlier != sample.remaining_mb:
            raise ValueError("conflicting_simultaneous_samples")

    def decision(state, interval, immediately, reason):
        return DualMonitorDecision(
            state=state,
            mail_poll_seconds=MAIL_POLL_SECONDS,
            account_poll_seconds=interval,
            account_read_due_now=immediately,
            booking_authorized=False,
            reason=reason,
        )

    # Login/cooldown guard always outranks new mail or traffic spikes.
    if provider_retry_after_seconds > 0:
        return decision("AUTH_BACKOFF", None, False, "provider_backoff")

    new_signal = mail_signal != "none"
    recently_awake = (
        last_activity_at is not None
        and 0 <= (now - last_activity_at).total_seconds() < ACTIVITY_WINDOW_SECONDS
    )
    if not (new_signal or network_active or recently_awake):
        return decision("STANDBY", None, False, "no_recent_activity")

    # A stale account snapshot is not a zero-GB proof. Acquire a new snapshot
    # read-only; never claim eligibility or issue a refill command.
    ordered = sorted((sample for sample in items if sample.timestamp <= now),
                     key=lambda sample: sample.timestamp)
    fresh = (
        bool(ordered)
        and (now - ordered[-1].timestamp).total_seconds() <= MAX_SAMPLE_AGE_SECONDS
    )
    if not fresh:
        return decision("ACTIVE", MIN_ACCOUNT_POLL_SECONDS, True, "fresh_snapshot_required")

    status = adaptive_status(ordered)
    interval = max(MIN_ACCOUNT_POLL_SECONDS, status.recommended_interval_seconds)
    if status.remaining_mb < 1000:
        return decision("REFILL_OBSERVE", interval, new_signal,
                        "low_volume_read_only")
    return decision("ACTIVE", interval, new_signal, status.pressure)
