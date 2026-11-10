"""LIDL-only offline regression: never refill at or above 1 GiB remaining."""
import pytest

from plugins.lidl_connect import LidlConnectWatcher


def watcher(mode="needed", threshold_mb=1024):
    return LidlConnectWatcher(
        username="offline-test", password="", threshold_mb=threshold_mb,
        dry_run=True, use_api=False, refill_selectors={},
        refill_mode=mode,
    )


def offer(remaining, *, free=True):
    total = 25 * 1024
    return {
        "used_mb": total - remaining,
        "total_mb": total,
        "refill_eligible": free,
        "refill_type": "FREE_UNLIMITED" if free else "PAID",
    }


@pytest.mark.parametrize("remaining,expected", [
    (0, True),
    (1, True),
    (512, True),
    (1023.99, True),
    (1024, False),
    (1024.01, False),
    (2048, False),
])
@pytest.mark.parametrize("mode", ["needed", "available"])
def test_free_offer_requires_strict_below_one_gib(mode, remaining, expected):
    assert watcher(mode).should_recharge_for_usage(offer(remaining)) is expected


@pytest.mark.parametrize("mode", ["needed", "available"])
@pytest.mark.parametrize("remaining,expected", [
    (500, True), (1023.99, True), (1024, False), (1500, False),
])
def test_custom_high_threshold_cannot_bypass_one_gib(mode, remaining, expected):
    assert watcher(mode, threshold_mb=2048).should_recharge_for_usage(offer(remaining)) is expected


@pytest.mark.parametrize("mode", ["needed", "available"])
def test_custom_lower_threshold_only_tightens_rule(mode):
    assert watcher(mode, threshold_mb=500).should_recharge_for_usage(offer(500)) is False
    assert watcher(mode, threshold_mb=500).should_recharge_for_usage(offer(499)) is True


def test_default_refill_mode_is_needed():
    assert watcher().refill_mode == "needed"


def test_missing_or_paid_offer_cannot_trigger_even_when_usage_low():
    instance = watcher()
    assert instance.should_recharge_for_usage(offer(200, free=False)) is False
    assert instance.should_recharge_for_usage({"used_mb": 25300, "total_mb": 25600}) is False


@pytest.mark.parametrize("bad", [
    {"used_mb": -1, "total_mb": 1024},
    {"used_mb": 1025, "total_mb": 1024},
    {"used_mb": float("nan"), "total_mb": 1024},
    {"used_mb": float("inf"), "total_mb": 1024},
    {"used_mb": True, "total_mb": 1024},
    {"used_mb": 10},
])
def test_invalid_usage_rejected(bad):
    candidate = dict(bad)
    candidate.update(refill_eligible=True, refill_type="FREE_UNLIMITED")
    assert watcher().should_recharge_for_usage(candidate) is False


@pytest.mark.asyncio
async def test_dry_run_no_booking_even_when_below_threshold(monkeypatch):
    instance = watcher()
    async def safe_usage():
        return offer(512)
    async def unsafe_booking(*args, **kwargs):
        raise AssertionError("no booking call allowed")
    monkeypatch.setattr(instance, "check_usage", safe_usage)
    monkeypatch.setattr(instance, "trigger_recharge", unsafe_booking)
    result = await instance.run()
    assert result.should_recharge is True
    assert result.recharge_triggered is False
