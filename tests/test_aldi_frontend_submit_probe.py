import base64
import json
from collections import deque
from unittest.mock import Mock

import pytest

import aldi_frontend_submit_probe as probe
from core.aldi_http_login import AUTH_API


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(probe.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(probe.time, 'sleep', lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(probe.watcher, 'ALDI_USER', 'PRIVATE_USERNAME')
    monkeypatch.setattr(probe.watcher, 'ALDI_PASS', 'PRIVATE_PASSWORD')
    return now


def event(method, request_id, **params):
    return {'message': json.dumps({'message': {
        'method': method, 'params': dict(params, requestId=request_id),
    }})}


def request(request_id):
    return event('Network.requestWillBeSent', request_id, request={
        'method': 'POST', 'url': AUTH_API + '?state=PRIVATE_URL',
        'headers': {'Content-Type': 'application/json', 'Cookie': 'PRIVATE_COOKIE'},
    })


def response(request_id, status=200):
    return event('Network.responseReceived', request_id, response={
        'status': status, 'url': AUTH_API,
    })


def credentials():
    return {'authId': 'PRIVATE_AUTH_ID', 'callbacks': [
        {'type': 'NameCallback', 'input': [{'name': 'IDToken1', 'value': 'PRIVATE_USERNAME'}]},
        {'type': 'PasswordCallback', 'input': [{'name': 'IDToken2', 'value': 'PRIVATE_PASSWORD'}]},
    ]}


def cached_driver(batches, post_data, body_reader):
    batches = deque(batches)
    driver = Mock()
    driver.get_log.side_effect = lambda kind: batches.popleft() if batches else []
    def cdp(method, params):
        if method == 'Network.getRequestPostData':
            return {'postData': json.dumps(post_data[params['requestId']])}
        assert method == 'Network.getResponseBody', 'Observer must never submit credentials or request ALDI'
        return body_reader(params['requestId'])
    driver.execute_cdp_cmd.side_effect = cdp
    return driver


@pytest.mark.parametrize('encoded', [False, True])
def test_observer_waits_for_same_response_and_body_without_logging_secrets(clock, encoded):
    attempts = []
    body = json.dumps({'tokenId': 'PRIVATE_TOKEN', 'authId': 'PRIVATE_AUTH_ID',
                       'successUrl': 'https://secret.invalid/PRIVATE_REDIRECT'})
    def body_reader(request_id):
        attempts.append(request_id)
        if len(attempts) == 1:
            raise RuntimeError('PRIVATE_TRANSIENT_CACHE_ERROR')
        return {'body': base64.b64encode(body.encode()).decode() if encoded else body,
                'base64Encoded': encoded}
    driver = cached_driver([
        [request('selected')],
        [response('selected')],
        [event('Network.loadingFinished', 'selected')],
    ], {'selected': credentials()}, body_reader)
    result = probe._capture_frontend_submit(driver, credentials(), timeout=2)
    assert result['request_received'] is True
    assert result['response_received'] is True and result['response_http_status'] == 200
    assert result['body_available'] is True and result['observation_timed_out'] is False
    assert result['response_shape']['has_token_id'] is True
    assert attempts == ['selected', 'selected']
    assert driver.get_log.call_count == 3
    assert 'PRIVATE' not in json.dumps(result) and 'secret.invalid' not in json.dumps(result)
    assert 'selected' not in json.dumps(result)
    driver.execute_script.assert_not_called()
    driver.get.assert_not_called()


def test_freezes_first_credential_post_ignoring_init_and_later_tree_requests(clock):
    body_ids = []
    def body_reader(request_id):
        body_ids.append(request_id)
        return {'body': json.dumps({'tokenId': 'PRIVATE_TOKEN'}), 'base64Encoded': False}
    driver = cached_driver([
        [request('init'), response('init'), request('selected'), request('continuation')],
        [response('continuation', 401), response('selected', 200)],
    ], {'init': {}, 'selected': credentials(), 'continuation': credentials()}, body_reader)
    result = probe._capture_frontend_submit(driver, credentials(), timeout=2)
    assert body_ids == ['selected']
    assert result['response_http_status'] == 200
    assert result['payload_shape']['same_auth_id_as_challenge'] is True
    post_ids = [item.args[1]['requestId'] for item in driver.execute_cdp_cmd.call_args_list
                if item.args[0] == 'Network.getRequestPostData']
    assert post_ids == ['init', 'selected']
    assert 'PRIVATE' not in json.dumps(result)


def test_missing_response_is_bounded_and_unknown_without_another_submit(clock):
    body_reader = Mock()
    driver = cached_driver([[request('selected')]], {'selected': credentials()}, body_reader)
    result = probe._capture_frontend_submit(driver, credentials(), timeout=.8)
    assert clock[0] == pytest.approx(.8)
    assert result['observation_timed_out'] is True
    assert result['response_received'] is False and result['body_available'] is False
    assert result['response_shape'] is None
    body_reader.assert_not_called()
    assert driver.execute_cdp_cmd.call_count == 1
    driver.execute_script.assert_not_called()


def test_unavailable_body_preserves_header_status_without_guessing_credentials(clock):
    body_reader = Mock(side_effect=RuntimeError('PRIVATE_UNAVAILABLE_BODY'))
    driver = cached_driver([[request('selected'), response('selected', 401)]],
                           {'selected': credentials()}, body_reader)
    result = probe._capture_frontend_submit(driver, credentials(), timeout=.8)
    assert clock[0] == pytest.approx(.8)
    assert result['response_received'] is True and result['response_http_status'] == 401
    assert result['body_available'] is False and result['observation_timed_out'] is True
    assert result['response_shape'] is None
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('body,encoded', [('PRIVATE_NON_JSON', False), ('[]', False), ('not-base64!', True)])
def test_unverified_body_does_not_report_no_token_as_authentication_failure(clock, body, encoded):
    driver = cached_driver([[request('selected'), response('selected')]], {'selected': credentials()},
                           lambda _: {'body': body, 'base64Encoded': encoded})
    result = probe._capture_frontend_submit(driver, credentials(), timeout=1)
    assert result['body_available'] is True
    assert result['response_shape'] is None
    assert 'PRIVATE' not in json.dumps(result)


def test_loading_failure_is_reported_without_exception_body_or_retry(clock):
    driver = cached_driver([[request('selected'), event('Network.loadingFailed', 'selected',
                           errorText='PRIVATE_PROXY_ERROR')]], {'selected': credentials()}, Mock())
    result = probe._capture_frontend_submit(driver, credentials(), timeout=1)
    assert result['request_failed'] is True and result['response_received'] is False
    assert result['observation_timed_out'] is False
    assert 'PRIVATE' not in json.dumps(result)
    assert driver.execute_cdp_cmd.call_count == 1


def test_initial_challenge_only_is_not_mistaken_for_credential_submission(clock):
    driver = cached_driver([[request('init'), response('init')]], {'init': {}}, Mock())
    assert probe._capture_frontend_submit(driver, credentials(), timeout=.8) is None
    assert clock[0] == pytest.approx(.8)
    assert driver.execute_cdp_cmd.call_count == 1
