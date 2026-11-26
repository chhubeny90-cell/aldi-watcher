"""Offline-only safety tests for the disabled NettoKOM LIFT provider slot."""
from dataclasses import replace
import pytest
from core.nettokom_lift import LiftObservation, assess_lift
from plugins.nettokom_lift import NettoKomLiftWatcher


@pytest.fixture
def eligible():
    return LiftObservation(account_verified=True, active_tariff="LIFT S",
                           remaining_gb="0,95", offer_size_gb="1",
                           offer_price_eur="0,00", offer_candidate_count=1,
                           offer_enabled=True, unresolved_transaction=False,
                           conflicting_terms=False)


def test_offline_candidate_never_authorizes_booking(eligible):
    result = assess_lift(eligible)
    assert result.simulated_offer_eligible is True
    assert result.reason == "offline_candidate_only"
    assert result.booking_authorized is False


@pytest.mark.parametrize("change,reason", [
    ({"account_verified": False}, "account_unverified"),
    ({"active_tariff": "SMART S"}, "active_lift_tariff_unverified"),
    ({"remaining_gb": "1"}, "threshold_not_reached"),
    ({"remaining_gb": "1,1"}, "threshold_not_reached"),
    ({"remaining_gb": "-0,1"}, "remaining_volume_unverified"),
    ({"remaining_gb": "NaN"}, "remaining_volume_unverified"),
    ({"remaining_gb": "bogus"}, "remaining_volume_unverified"),
    ({"remaining_gb": 0.8}, "remaining_volume_unverified"),
    ({"offer_size_gb": "2"}, "not_exactly_one_gb"),
    ({"offer_price_eur": "0,01"}, "price_not_explicit_zero"),
    ({"offer_price_eur": None}, "price_not_explicit_zero"),
    ({"offer_candidate_count": 2}, "offer_ambiguous"),
    ({"offer_candidate_count": True}, "offer_ambiguous"),
    ({"offer_enabled": False}, "offer_disabled"),
    ({"unresolved_transaction": True}, "unresolved_transaction"),
    ({"conflicting_terms": True}, "conflicting_offer_terms"),
])
def test_fail_closed(eligible, change, reason):
    result = assess_lift(replace(eligible, **change))
    assert result.simulated_offer_eligible is False
    assert result.booking_authorized is False
    assert result.reason == reason


def test_lift_sizes(eligible):
    for tariff in ("LIFT S", "LIFT M", "LIFT L"):
        assert assess_lift(replace(eligible, active_tariff=tariff)).simulated_offer_eligible


@pytest.mark.asyncio
async def test_disabled_plugin_refuses_live_read_and_booking():
    watcher = NettoKomLiftWatcher("fixture", "", 1000, dry_run=False)
    assert watcher.provider_name == "nettokom_lift"
    assert watcher.should_recharge_for_usage({"used_mb": 9999, "total_mb": 10000}) is False
    with pytest.raises(RuntimeError, match="live_usage_unavailable"):
        await watcher.check_usage()
    with pytest.raises(RuntimeError, match="live_booking_disabled"):
        await watcher.trigger_recharge()
    result = await watcher.run()
    assert result.success is False
    assert result.recharge_triggered is False
