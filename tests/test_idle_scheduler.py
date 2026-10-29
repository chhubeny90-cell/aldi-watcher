from core.idle_scheduler import Mode, decide
import pytest


def test_regular_check_at_90_seconds():
    assert not decide(now=89, last_measured_activity=0, last_check=0).check_due
    result = decide(now=90, last_measured_activity=80, last_check=0)
    assert result.mode == Mode.ACTIVE and result.check_due


def test_measured_inactivity_causes_sleep():
    result = decide(now=3600, last_measured_activity=0, last_check=0)
    assert result.mode == Mode.SLEEP and not result.check_due


def test_mail_wakes_idle_scheduler():
    result = decide(now=3600, last_measured_activity=0, last_check=0, consumed_mail=True)
    assert result.mode == Mode.ACTIVE and result.check_due


def test_unknown_activity_is_not_assumed_idle():
    assert decide(now=7200, last_measured_activity=None, last_check=7100).mode == Mode.ACTIVE


def test_unresolved_booking_prevents_duplicate_attempt():
    result = decide(now=3600, last_measured_activity=0, last_check=0,
                    consumed_mail=True, unresolved_booking=True)
    assert result.mode == Mode.SLEEP and not result.check_due


@pytest.mark.parametrize("kwargs", [
    {"now": -1, "last_measured_activity": 0, "last_check": 0},
    {"now": 10, "last_measured_activity": 11, "last_check": 0},
    {"now": 10, "last_measured_activity": 0, "last_check": 11},
])
def test_invalid_timestamps_rejected(kwargs):
    with pytest.raises(ValueError):
        decide(**kwargs)
