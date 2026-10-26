"""Offline checks for the dual-signal read-only monitoring policy."""
from datetime import datetime, timedelta, timezone

import pytest

from core.adaptive_monitor import UsageSample
from core.dual_monitor_policy import schedule_dual_monitor


NOW = datetime(2026, 10, 26, 0, 30, tzinfo=timezone.utc)


def sample(seconds_ago, remaining):
    return UsageSample(NOW - timedelta(seconds=seconds_ago), remaining)


def test_idle_means_mail_only_not_aldi():
    result = schedule_dual_monitor(now=NOW)
    assert result.state == "STANDBY"
    assert result.mail_poll_seconds == 60
    assert result.account_poll_seconds is None
    assert not result.account_read_due_now
    assert not result.booking_authorized


def test_consumed_mail_wakes_read_only_account_check():
    result = schedule_dual_monitor(now=NOW, mail_signal="consumed")
    assert result.state == "ACTIVE"
    assert result.account_read_due_now
    assert result.account_poll_seconds == 60
    assert not result.booking_authorized


def test_warning_wakes_monitor_but_does_not_book():
    result = schedule_dual_monitor(now=NOW, mail_signal="80_percent")
    assert result.account_read_due_now
    assert result.booking_authorized is False


def test_active_traffic_uses_adaptive_sampling_but_caps_rate():
    result = schedule_dual_monitor(
        now=NOW, network_active=True,
        samples=(sample(300, 1800), sample(0, 1300)),
    )
    assert result.state == "ACTIVE"
    assert result.account_poll_seconds == 60
    assert not result.booking_authorized


def test_low_volume_never_authorizes_a_refill():
    result = schedule_dual_monitor(
        now=NOW, mail_signal="consumed", samples=(sample(0, 500),),
    )
    assert result.state == "REFILL_OBSERVE"
    assert result.account_poll_seconds == 60
    assert result.booking_authorized is False


def test_exactly_1000_mb_is_not_below_threshold():
    result = schedule_dual_monitor(
        now=NOW, network_active=True, samples=(sample(0, 1000),),
    )
    assert result.state == "ACTIVE"
    assert not result.booking_authorized


def test_stale_account_sample_cannot_trigger_low_volume_status():
    result = schedule_dual_monitor(
        now=NOW, mail_signal="consumed", samples=(sample(301, 0),),
    )
    assert result.state == "ACTIVE"
    assert result.reason == "fresh_snapshot_required"
    assert result.account_read_due_now
    assert not result.booking_authorized


def test_recent_wakeup_keeps_monitor_active_until_idle_timeout():
    awake = schedule_dual_monitor(
        now=NOW, last_activity_at=NOW - timedelta(seconds=599),
    )
    asleep = schedule_dual_monitor(
        now=NOW, last_activity_at=NOW - timedelta(seconds=600),
    )
    assert awake.state == "ACTIVE"
    assert asleep.state == "STANDBY"


def test_provider_backoff_blocks_account_even_when_mail_arrives():
    result = schedule_dual_monitor(
        now=NOW, mail_signal="consumed", network_active=True,
        provider_retry_after_seconds=120,
    )
    assert result.state == "AUTH_BACKOFF"
    assert result.mail_poll_seconds == 60
    assert result.account_poll_seconds is None
    assert not result.booking_authorized


@pytest.mark.parametrize("signal", ("BOOK", "anything", ""))
def test_unknown_signals_are_rejected(signal):
    with pytest.raises(ValueError, match="invalid_mail_signal"):
        schedule_dual_monitor(now=NOW, mail_signal=signal)


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone_aware_now_required"):
        schedule_dual_monitor(now=datetime(2026, 10, 26))


@pytest.mark.parametrize("remaining", [-1, float("nan"), float("inf"), True])
def test_invalid_volume_is_rejected(remaining):
    with pytest.raises(ValueError, match="invalid_remaining_volume"):
        schedule_dual_monitor(now=NOW, mail_signal="consumed", samples=(UsageSample(NOW, remaining),))


@pytest.mark.parametrize("delay", [-1, float("nan"), float("inf"), True, None])
def test_invalid_backoff_is_rejected(delay):
    with pytest.raises(ValueError, match="invalid_provider_backoff"):
        schedule_dual_monitor(now=NOW, provider_retry_after_seconds=delay)


def test_future_reading_is_rejected():
    with pytest.raises(ValueError, match="future_sample_rejected"):
        schedule_dual_monitor(now=NOW, mail_signal="consumed",
                              samples=(UsageSample(NOW + timedelta(seconds=1), 0),))


def test_conflicting_readings_at_same_instant_are_rejected():
    with pytest.raises(ValueError, match="conflicting_simultaneous_samples"):
        schedule_dual_monitor(now=NOW, mail_signal="consumed",
                              samples=(sample(0, 0), sample(0, 5000)))


def test_matching_duplicates_stay_read_only():
    state = schedule_dual_monitor(now=NOW, mail_signal="consumed",
                                  samples=(sample(0, 500), sample(0, 500)))
    assert state.state == "REFILL_OBSERVE"
    assert state.booking_authorized is False


def test_future_activity_is_rejected():
    with pytest.raises(ValueError, match="future_activity_rejected"):
        schedule_dual_monitor(now=NOW, last_activity_at=NOW + timedelta(seconds=30))
