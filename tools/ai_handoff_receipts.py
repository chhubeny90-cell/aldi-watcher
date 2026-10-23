"""Validate a counterpart ACK read through an authenticated GitHub connector.

This pure validator does not send, poll or authenticate a model. Its caller must
fetch the comment from the stated repository/thread through the connected API.
A sender's own write/readback is storage proof only, never counterpart receipt.
"""
import json
import re


def verify_ack(task, comment, *, expected_author):
    def blocked(reason):
        return {'status': 'NOT_ACKNOWLEDGED', 'reason': reason}
    if not isinstance(comment, dict):
        return blocked('interface_unavailable_or_no_receipt')
    if not isinstance(task, dict) or not re.fullmatch(r'[0-9a-f]{40}', str(task.get('commit', ''))):
        return blocked('invalid_task_commit')
    # Both identities must originate from the authenticated transport. An absent
    # sender is not evidence that the commenter is an independent counterpart.
    identity = r'[A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?'
    if (not isinstance(task.get('sender_login'), str)
            or re.fullmatch(identity, task['sender_login']) is None
            or not isinstance(expected_author, str)
            or re.fullmatch(identity, expected_author) is None):
        return blocked('handoff_identity_unverified')
    author = comment.get('author') or comment.get('user')
    if not isinstance(author, dict) or author.get('login') != expected_author:
        return blocked('counterpart_identity_mismatch')
    if expected_author.casefold() == task['sender_login'].casefold():
        return blocked('sender_readback_is_not_counterpart_ack')
    # Bind the ACK to the exact PR/issue where the task was delivered.
    # A matching nonce posted to another repository thread is not a receipt.
    repository = task.get('repository')
    kind = task.get('thread_kind')
    number = task.get('thread_number')
    if (not isinstance(repository, str)
            or re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) is None
            or kind not in ('issues', 'pull')
            or type(number) is not int or number < 1):
        return blocked('handoff_thread_unverified')
    url = comment.get('html_url') or comment.get('url')
    expected = f'https://github.com/{repository}/{kind}/{number}#issuecomment-'
    if (not isinstance(url, str)
            or re.fullmatch(re.escape(expected) + r'[1-9][0-9]*', url) is None):
        return blocked('receipt_location_unverified')
    try:
        payload = json.loads(comment.get('body', ''))
    except (TypeError, ValueError):
        return blocked('structured_ack_missing')
    if not isinstance(payload, dict) or payload.get('type') != 'KI_ACK_V1':
        return blocked('structured_ack_missing')
    if any(payload.get(k) != task.get(k) or not task.get(k)
           for k in ('task_id', 'commit', 'challenge', 'owner')):
        return blocked('ack_task_commit_or_challenge_mismatch')
    return {'status': 'ACKNOWLEDGED', 'receipt_url': url,
            'review_status': 'PENDING', 'completion_status': 'OPEN'}
