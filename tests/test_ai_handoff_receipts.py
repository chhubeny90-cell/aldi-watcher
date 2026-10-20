import json
import pytest
from tools.ai_handoff_receipts import verify_ack


def task():
    return {'task_id': 'KI-TEST-001', 'commit': 'a' * 40, 'challenge': 'synthetic-nonce',
            'owner': 'codex', 'sender_login': 'sender', 'repository': 'example/watcher',
            'thread_kind': 'issues', 'thread_number': 1}


def receipt():
    return {'author': {'login': 'counterpart'},
            'html_url': 'https://github.com/example/watcher/issues/1#issuecomment-2',
            'body': json.dumps({'type': 'KI_ACK_V1', **task()})}


@pytest.mark.parametrize(('kind', 'number'), [
    ('issues', 2), ('pull', 1), ('releases', 1), ('issues', 0),
    ('issues', True), ('issues', 1.0), ('issues', '1'),
])
def test_receipt_must_match_exact_authenticated_thread(kind, number):
    data = task(); data['thread_kind'] = kind; data['thread_number'] = number
    result = verify_ack(data, receipt(), expected_author='counterpart')
    assert result['status'] == 'NOT_ACKNOWLEDGED'


@pytest.mark.parametrize('url', [
    'https://github.com/example/watcher/issues/2#issuecomment-2',
    'https://github.com/example/watcher/pull/1#issuecomment-2',
    'https://github.com/example/watcher/issues/1#issuecomment-x',
    'https://github.com/example/watcher/issues/1#issuecomment-2-extra',
    'https://github.com/example/watcher/issues/1?other=1#issuecomment-2',
    'https://github.com/example/watcher/issues/1#issuecomment-0',
    'https://github.com/other/watcher/issues/1#issuecomment-2',
])
def test_unrelated_thread_or_malformed_comment_link_cannot_ack(url):
    data = receipt(); data['html_url'] = url
    result = verify_ack(task(), data, expected_author='counterpart')
    assert result['reason'] == 'receipt_location_unverified'


def test_pr_thread_ack_is_valid_but_not_an_approval():
    t = task(); t['thread_kind'] = 'pull'; t['thread_number'] = 121
    c = receipt(); c['html_url'] = 'https://github.com/example/watcher/pull/121#issuecomment-8'
    result = verify_ack(t, c, expected_author='counterpart')
    assert result['status'] == 'ACKNOWLEDGED'
    assert result['review_status'] == 'PENDING'


def test_missing_thread_metadata_cannot_ack():
    t = task(); t.pop('thread_number')
    assert verify_ack(t, receipt(), expected_author='counterpart')['reason'] == 'handoff_thread_unverified'


def test_missing_interface_does_not_claim_delivery():
    assert verify_ack(task(), None, expected_author='counterpart')['status'] == 'NOT_ACKNOWLEDGED'


def test_write_read_by_sender_is_not_counterpart_receipt():
    data = receipt(); data['author']['login'] = 'sender'
    assert verify_ack(task(), data, expected_author='sender')['reason'] == 'sender_readback_is_not_counterpart_ack'


@pytest.mark.parametrize('key,value', [('commit', 'b' * 40), ('challenge', 'old'), ('owner', 'other'), ('task_id', 'old')])
def test_ack_cannot_be_replayed_for_another_task(key, value):
    data = receipt(); body = json.loads(data['body']); body[key] = value; data['body'] = json.dumps(body)
    assert verify_ack(task(), data, expected_author='counterpart')['status'] == 'NOT_ACKNOWLEDGED'


def test_counterpart_ack_is_not_review_approval_or_task_completion():
    result = verify_ack(task(), receipt(), expected_author='counterpart')
    assert result['status'] == 'ACKNOWLEDGED'
    assert result['review_status'] == 'PENDING' and result['completion_status'] == 'OPEN'


def test_wrong_author_cannot_claim_delivery():
    assert verify_ack(task(), receipt(), expected_author='different')['status'] == 'NOT_ACKNOWLEDGED'


@pytest.mark.parametrize('sender', [None, '', ' ', 1, [], 'sender/other'])
def test_unknown_sender_never_allows_own_readback_as_ack(sender):
    data = task()
    if sender is None: data.pop('sender_login')
    else: data['sender_login'] = sender
    assert verify_ack(data, receipt(), expected_author='counterpart')['reason'] == 'handoff_identity_unverified'


def test_sender_case_variation_is_still_self_ack():
    data = task(); data['sender_login'] = 'CounterPart'
    assert verify_ack(data, receipt(), expected_author='counterpart')['reason'] == 'sender_readback_is_not_counterpart_ack'
