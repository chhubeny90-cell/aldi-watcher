from datetime import datetime, timedelta

from core.adaptive_monitor import UsageSample, adaptive_status


def sample(base, minutes, remaining):
    return UsageSample(base + timedelta(minutes=minutes), remaining)


def test_idle_monitor_uses_slow_interval():
    base = datetime(2026, 10, 10, 2, 0, 0)
    status = adaptive_status([sample(base, 0, 5000)])
    assert status.burn_rate_mb_per_min == 0
    assert status.eta_to_refill_min is None
    assert status.recommended_interval_seconds == 300
    assert status.pressure == "idle"


def test_aggressive_consumption_speeds_up_polling():
    base = datetime(2026, 10, 10, 2, 0, 0)
    status = adaptive_status([
        sample(base, 0, 1800),
        sample(base, 5, 1300),
    ])
    assert status.burn_rate_mb_per_min == 100
    assert status.eta_to_refill_min == 3
    assert status.recommended_interval_seconds == 15
    assert status.pressure == "critical"


def test_refill_zone_is_checked_fast():
    base = datetime(2026, 10, 10, 2, 0, 0)
    status = adaptive_status([sample(base, 0, 950)])
    assert status.eta_to_refill_min == 0
    assert status.recommended_interval_seconds == 15
    assert status.pressure == "refill_zone"


def test_refill_reset_is_not_learned_as_negative_consumption():
    base = datetime(2026, 10, 10, 2, 0, 0)
    status = adaptive_status([
        sample(base, 0, 1050),
        sample(base, 1, 2050),  # successful 1 GB refill/reset
        sample(base, 3, 1950),
    ])
    assert status.burn_rate_mb_per_min == 50
    assert status.eta_to_refill_min == 19
    assert status.recommended_interval_seconds == 60
    assert status.pressure == "medium"


def test_uses_median_to_reduce_single_spike_noise():
    base = datetime(2026, 10, 10, 2, 0, 0)
    status = adaptive_status([
        sample(base, 0, 5000),
        sample(base, 1, 4900),
        sample(base, 2, 4800),
        sample(base, 3, 3800),  # one noisy/spiky minute
        sample(base, 4, 3700),
    ])
    assert status.burn_rate_mb_per_min == 100
