import copy
import json

import pytest

from tools.ki_box_receipts import HandoffError, assess_receipts, validate_task


SHA = "d0bb785bc66d0bc07213c7a409d69ad130ab14a7"


@pytest.fixture
def task():
    return {
        "repository": "chhubeny90-cell/aldi-watcher",
        "thread_kind": "pull",
        "thread_number": 321,
        "commit": SHA,
        "task_id": "WATCH-KIBOX-20261021",
        "challenge": "trustedChallenge0123456789",
        "sender_login": "chhubeny90-cell",
        "recipients": {
            "copilot": "chatgpt-codex-connector[bot]",
            "gemini": None,
            "perplexity": None,
            "openai": None,
        },
    }


def acknowledgement(task):
    return {
        "user": {"login": "chatgpt-codex-connector[bot]"},
        "html_url": "https://github.com/chhubeny90-cell/aldi-watcher/pull/321#issuecomment-42",
        "body": json.dumps({
            "type": "KI_ACK_V1",
            "task_id": task["task_id"],
            "commit": task["commit"],
            "challenge": task["challenge"],
            "provider": "copilot",
            "owner": task["sender_login"],
        }),
    }


def test_initial_state_fails_closed(task):
    output = assess_receipts(task, [])
    assert output["providers"]["copilot"]["status"] == "AWAITING_ACK"
    assert output["providers"]["gemini"]["status"] == "NOT_CONNECTED"
    assert output["providers"]["perplexity"]["status"] == "NOT_CONNECTED"
    assert output["external_model_execution"] == "NOT_PROVEN"
    assert output["aldi_live_status"] == "BLOCKED"


def test_matching_github_counterpart_ack_not_completion(task):
    output = assess_receipts(task, [acknowledgement(task)])
    assert output["providers"]["copilot"] == {
        "status": "ACKNOWLEDGED",
        "receipt_url": "https://github.com/chhubeny90-cell/aldi-watcher/pull/321#issuecomment-42",
        "review_status": "PENDING",
        "completion_status": "OPEN",
    }


@pytest.mark.parametrize("bad_url", [
    "https://github.com/chhubeny90-cell/aldi-watcher/issues/321#issuecomment-42",
    "https://github.com/chhubeny90-cell/aldi-watcher/pull/322#issuecomment-42",
    "https://github.com/other/aldi-watcher/pull/321#issuecomment-42",
    "https://github.com/chhubeny90-cell/aldi-watcher/pull/321#issuecomment-0",
    "https://github.com/chhubeny90-cell/aldi-watcher/pull/321#issuecomment-42?source=copy",
])
def test_wrong_thread_not_acknowledged(task, bad_url):
    comment = acknowledgement(task)
    comment["html_url"] = bad_url
    assert assess_receipts(task, [comment])["providers"]["copilot"]["status"] == "AWAITING_ACK"


@pytest.mark.parametrize("field,value", [
    ("commit", "a" * 40), ("challenge", "stolenDifferentChallenge"),
    ("task_id", "WATCH-OTHER"), ("owner", "someone-else"),
    ("provider", "gemini"), ("type", "NOT_AN_ACK"),
])
def test_mismatched_envelope_not_acknowledged(task, field, value):
    comment = acknowledgement(task)
    obj = json.loads(comment["body"])
    obj[field] = value
    comment["body"] = json.dumps(obj)
    assert assess_receipts(task, [comment])["providers"]["copilot"]["status"] == "AWAITING_ACK"


def test_owner_readback_is_not_counterpart_ack(task):
    comment = acknowledgement(task)
    comment["user"]["login"] = task["sender_login"]
    assert assess_receipts(task, [comment])["providers"]["copilot"]["status"] == "AWAITING_ACK"


def test_plain_markdown_review_is_not_structured_ack(task):
    comment = acknowledgement(task)
    comment["body"] = "Codex Review: Didn't find any major issues."
    assert assess_receipts(task, [comment])["providers"]["copilot"]["status"] == "AWAITING_ACK"


def test_duplicate_json_keys_block(task):
    comment = acknowledgement(task)
    obj = json.loads(comment["body"])
    comment["body"] = json.dumps(obj)[:-1] + ',"provider":"copilot"}'
    assert assess_receipts(task, [comment])["providers"]["copilot"]["status"] == "AWAITING_ACK"


@pytest.mark.parametrize("bad_thread", [0, True, 1.5, "321", -1])
def test_invalid_thread_types_block(task, bad_thread):
    task["thread_number"] = bad_thread
    with pytest.raises(HandoffError, match="invalid_thread_number"):
        validate_task(task)


def test_sender_cannot_be_recipient(task):
    task["recipients"]["gemini"] = task["sender_login"]
    with pytest.raises(HandoffError, match="invalid_recipient_identity"):
        validate_task(task)


def test_non_list_comments_are_invalid(task):
    with pytest.raises(HandoffError, match="comments_must_be_list"):
        assess_receipts(task, {"user": "untrusted"})


def test_gemini_perplexity_have_no_unverified_delivery(task):
    result = assess_receipts(task, [acknowledgement(task)])
    assert result["providers"]["gemini"]["status"] == "NOT_CONNECTED"
    assert result["providers"]["perplexity"]["status"] == "NOT_CONNECTED"
