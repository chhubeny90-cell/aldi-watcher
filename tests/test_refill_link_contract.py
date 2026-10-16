import concurrent.futures
import pytest
import refill_link_notify as notify
from refill_link_accept import accept


@pytest.fixture
def request_data(monkeypatch, tmp_path):
    key = 'test-only-key-' * 4
    monkeypatch.setenv('ALDI_LINK_SIGNING_KEY', key)
    token = notify._token(now=1000)
    return token, dict(key=key, profile=notify.PROFILE, database=tmp_path / 'state.db', now=1001)


def test_accept_is_not_booking_and_replay_is_rejected(request_data):
    token, args = request_data
    assert accept(token, **args)['provider_action'] is False
    with pytest.raises(ValueError, match='already_accepted'):
        accept(token, **args)


@pytest.mark.parametrize('change', ['tamper', 'wrong_key', 'wrong_profile', 'expired', 'future'])
def test_rejections(request_data, change):
    token, args = request_data
    if change == 'tamper': token = ('A' if token[0] != 'A' else 'B') + token[1:]
    if change == 'wrong_key': args['key'] = 'wrong-key' * 8
    if change == 'wrong_profile': args['profile'] = 'other'
    if change == 'expired': args['now'] = 1000 + notify.TOKEN_TTL_SECONDS
    if change == 'future': args['now'] = 999
    with pytest.raises(ValueError): accept(token, **args)


def test_concurrent_single_use(request_data):
    token, args = request_data
    def attempt(_):
        try:
            accept(token, **args)
            return True
        except ValueError as exc:
            assert str(exc) == 'already_accepted'
            return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(16))) == 1


def test_no_alert_does_not_send(monkeypatch):
    monkeypatch.setattr(notify, '_read_actionable_count', lambda: 0)
    monkeypatch.setattr(notify, '_send', lambda _: pytest.fail('unexpected email'))
    assert notify.main() == 0
