import pytest
from core.idle_scheduler import Mode
from core.offline_watcher_replay import RecordedSignal, replay

@pytest.mark.parametrize("provider", ["ALDI", "LIDL"])
def test_offline_mail_wakeup(provider):
    result = replay(RecordedSignal(provider, 4000, 0, 3900, consumed_mail=True))
    assert result.mode == Mode.ACTIVE and result.check_due

@pytest.mark.parametrize("provider", ["ALDI", "LIDL"])
def test_offline_idle(provider):
    result = replay(RecordedSignal(provider, 3600, 0, 3500))
    assert result.mode == Mode.SLEEP and not result.check_due

@pytest.mark.parametrize("provider", ["ALDI", "LIDL"])
def test_offline_interval(provider):
    result = replay(RecordedSignal(provider, 190, 100, 100))
    assert result.mode == Mode.ACTIVE and result.check_due

def test_unknown_provider_rejected():
    with pytest.raises(ValueError, match="unsupported_provider"):
        replay(RecordedSignal("OTHER", 100, 0, 0))

def test_unresolved_operation_prevents_checks():
    result = replay(RecordedSignal("LIDL", 4000, 0, 0, consumed_mail=True,
                                   unresolved_booking=True))
    assert result.mode == Mode.SLEEP and not result.check_due
