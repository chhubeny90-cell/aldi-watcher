"""Verify shared timing rules apply to both providers without portal calls."""
import pytest

from core.idle_scheduler import Mode, decide


@pytest.mark.parametrize("provider", ["ALDI", "LIDL"])
def test_provider_wakeup_by_consumption_mail(provider):
    # Provider identity is deliberately irrelevant to the shared scheduler.
    result = decide(now=4000, last_measured_activity=0, last_check=3800,
                    consumed_mail=True)
    assert result.mode is Mode.ACTIVE
    assert result.check_due is True
    assert result.reason == "mail_wakeup"


@pytest.mark.parametrize("provider", ["ALDI", "LIDL"])
def test_provider_sleeps_after_measured_hour_of_inactivity(provider):
    result = decide(now=3600, last_measured_activity=0, last_check=3500)
    assert result.mode is Mode.SLEEP
    assert result.check_due is False


@pytest.mark.parametrize("provider", ["ALDI", "LIDL"])
def test_provider_90_second_check(provider):
    result = decide(now=190, last_measured_activity=100, last_check=100)
    assert result.mode is Mode.ACTIVE
    assert result.check_due is True
