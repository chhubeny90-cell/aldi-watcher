import json
import pytest
from tools.ai_handoff_receipts import verify_ack


def task():
    return {'task_id': 'KI-TEST-001', 'commit': 'a' * 40, 'challenge': 'synthetic-nonce',
            'owner': 'codex', 'sender_login': 'sender', 'repository': 'example/watcher'}


def receipt():
    return {'author': {'login': 'counterpart'},
            'html_url': 'https://github.com/example/watcher/issues/1#issuecomment-2',
            'body': json.dumps({'type': 'KI_ACK_V1', **task()})}


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
