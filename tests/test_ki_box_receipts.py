import copy
from email.message import Message
from http.client import BadStatusLine, HTTPResponse, IncompleteRead
import io
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPHandler, HTTPSHandler, build_opener
from urllib.response import addinfourl

import pytest

from tools import ki_box_receipts as receipts
from tools.ki_box_receipts import HandoffError, _NoRedirectHandler, assess_receipts, validate_task


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
        "sender_id": 259501947,
        "recipients": {
            "copilot": {"login": "chatgpt-codex-connector[bot]", "id": 199175422},
            "gemini": None,
            "perplexity": None,
            "openai": None,
        },
    }


def acknowledgement(task):
    return {
        "id": 42,
        "user": {"login": "chatgpt-codex-connector[bot]", "id": 199175422},
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


def test_github_bearer_token_redirect_is_blocked():
    handler = _NoRedirectHandler()
    with pytest.raises(HandoffError, match="redirect_not_allowed"):
        handler.redirect_request(None, None, 302, "Found", {}, "https://malicious.example/collect")


def status(task, comments):
    return assess_receipts(task, comments)["providers"]["copilot"]["status"]


def test_bot_identity_and_case_insensitive_login_with_durable_id(task):
    task["recipients"]["copilot"]["login"] = "ChatGPT-Codex-Connector[bot]"
    assert validate_task(task) == task
    assert status(task, [acknowledgement(task)]) == "ACKNOWLEDGED"


@pytest.mark.parametrize("bad_id", [None, True, False, 0, -1, "199175422", 1.0, 1234])
def test_reclaimed_login_or_invalid_author_id_never_acknowledged(task, bad_id):
    comment = acknowledgement(task)
    comment["user"]["id"] = bad_id
    assert status(task, [comment]) == "AWAITING_ACK"


@pytest.mark.parametrize("bad_login", [None, [], 123, "wrong-account"])
def test_malformed_author_does_not_break_audit(task, bad_login):
    comment = acknowledgement(task)
    comment["user"]["login"] = bad_login
    assert status(task, [comment]) == "AWAITING_ACK"


@pytest.mark.parametrize("bad_id", [None, True, 0, -1, "42", 43])
def test_comment_id_must_match_anchor(task, bad_id):
    comment = acknowledgement(task)
    comment["id"] = bad_id
    assert status(task, [comment]) == "AWAITING_ACK"


@pytest.mark.parametrize("bad_id", [None, True, 0, -1, "199175422", 1.0])
def test_recipient_requires_positive_integer_id(task, bad_id):
    task["recipients"]["copilot"]["id"] = bad_id
    with pytest.raises(HandoffError, match="invalid_recipient_identity"):
        validate_task(task)


@pytest.mark.parametrize("bad_id", [None, True, 0, -1, "259501947"])
def test_sender_requires_positive_integer_id(task, bad_id):
    task["sender_id"] = bad_id
    with pytest.raises(HandoffError, match="invalid_sender_id"):
        validate_task(task)


@pytest.mark.parametrize("recipient", [
    {"login": "different-login", "id": 259501947},
    {"login": "CHHUBENY90-CELL", "id": 123},
    {"login": "different-login", "id": 199175422},
    {"login": "ChatGPT-Codex-Connector[bot]", "id": 123},
])
def test_each_provider_requires_independent_identity(task, recipient):
    task["recipients"]["gemini"] = recipient
    with pytest.raises(HandoffError, match="invalid_recipient_identity"):
        validate_task(task)


def test_login_only_legacy_task_fails_closed(task):
    task["recipients"]["copilot"] = "chatgpt-codex-connector[bot]"
    with pytest.raises(HandoffError, match="invalid_recipient_identity"):
        validate_task(task)


def test_duplicate_receipt_observation_is_idempotent_and_never_completes(task):
    comment = acknowledgement(task)
    once = assess_receipts(task, [comment])
    assert assess_receipts(task, [comment, copy.deepcopy(comment)]) == once
    assert assess_receipts(task, [comment]) == once
    assert once["providers"]["copilot"]["completion_status"] == "OPEN"
    assert once["external_model_execution"] == "NOT_PROVEN"


@pytest.mark.parametrize("body", [
    "[]", "null", "true", "{", "{\"extra\":NaN}",
    "[" * 2000 + "]" * 2000, " " * 8193,
])
def test_malformed_or_excessive_receipt_json_not_acknowledged(task, body):
    comment = acknowledgement(task)
    comment["body"] = body
    assert status(task, [comment]) == "AWAITING_ACK"


class MemoryResponse(io.BytesIO):
    def __init__(self, data, url, status=200):
        super().__init__(data)
        self.url = url
        self.status = status
        self.headers = Message()

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


def install_pages(monkeypatch, pages):
    """Pure memory transport; no socket or external service can be contacted."""
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            value = pages[len(calls) - 1]
            if isinstance(value, Exception):
                raise value
            if callable(value):
                return value(request)
            body = json.dumps(value).encode() if not isinstance(value, bytes) else value
            return MemoryResponse(body, request.full_url)

    monkeypatch.setattr(receipts, "build_opener", lambda *args: Opener())
    return calls


def test_fetch_requests_only_canonical_github_get_and_assesses_real_response(task, monkeypatch):
    calls = install_pages(monkeypatch, [[acknowledgement(task)]])
    comments = receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert status(task, comments) == "ACKNOWLEDGED"
    request, timeout = calls[0]
    assert request.full_url == (
        "https://api.github.com/repos/chhubeny90-cell/aldi-watcher/issues/321/"
        "comments?per_page=100&page=1"
    )
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer synthetic-test-token"
    assert request.get_header("X-github-api-version") == "2022-11-28"
    assert timeout == 15


@pytest.mark.parametrize("repository", ["owner/.github", "owner/.hidden-repo", "owner/repo.name"])
def test_valid_dot_prefixed_repository_uses_canonical_api_path(task, monkeypatch, repository):
    task["repository"] = repository
    calls = install_pages(monkeypatch, [[]])
    assert receipts.fetch_authenticated_comments(task, "synthetic-test-token") == []
    assert calls[0][0].full_url == (
        f"https://api.github.com/repos/{repository}/issues/321/comments?per_page=100&page=1"
    )


def memory_http_response(request, wire_body, headers):
    """Real http.client framing over a finite byte stream, with no socket I/O."""
    entries = headers.items() if isinstance(headers, dict) else headers
    wire = b"HTTP/1.1 200 OK\r\n" + b"".join(
        f"{name}: {value}\r\n".encode("ascii") for name, value in entries
    ) + b"\r\n" + wire_body

    class FakeSocket:
        def makefile(self, mode):
            assert mode == "rb"
            return io.BytesIO(wire)

    response = HTTPResponse(FakeSocket(), method="GET")
    response.begin()
    response.url = request.full_url
    return response


@pytest.mark.parametrize("contains_ack", [False, True])
@pytest.mark.parametrize("later_page", [False, True])
def test_short_content_length_valid_json_never_produces_audit_success(
        task, monkeypatch, tmp_path, capsys, contains_ack, later_page):
    # read(amt) silently returns these syntactically complete JSON bytes even
    # though HTTPResponse still expects more bytes from the declared body.
    body = json.dumps([acknowledgement(task)] if contains_ack else []).encode()
    pages = []
    if later_page:
        pages.append([acknowledgement(task)] + [{"id": n} for n in range(99)])
    pages.append(lambda request: memory_http_response(
        request, body, {"Content-Length": len(body) + 999}
    ))
    calls = install_pages(monkeypatch, pages)
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task), encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-test-token")
    assert receipts.main(["--task", str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ki-box-receipts: receipt_audit_failed\n"
    assert len(calls) == (2 if later_page else 1)


@pytest.mark.parametrize("framing", ["content_length", "close_delimited", "chunked", "uppercase_chunked"])
def test_real_http_response_complete_framing_preserves_valid_receipt(task, monkeypatch, framing):
    body = json.dumps([acknowledgement(task)]).encode()
    if framing == "content_length":
        headers = {"Content-Length": len(body)}
        wire_body = body
    elif framing in ("chunked", "uppercase_chunked"):
        headers = {"Transfer-Encoding": "CHUNKED" if framing == "uppercase_chunked" else "chunked"}
        wire_body = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
    else:
        headers = {"Connection": "close"}
        wire_body = body
    calls = install_pages(monkeypatch, [lambda request: memory_http_response(request, wire_body, headers)])
    comments = receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert status(task, comments) == "ACKNOWLEDGED"
    assert len(calls) == 1


def test_truncated_chunked_valid_json_body_is_rejected(task, monkeypatch):
    # JSON alone is complete, but the required terminal HTTP chunk never arrived.
    body = b"2\r\n[]\r\n"
    calls = install_pages(monkeypatch, [lambda request: memory_http_response(
        request, body, {"Transfer-Encoding": "chunked"}
    )])
    with pytest.raises(HandoffError, match="^github_comments_unavailable$"):
        receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert len(calls) == 1


@pytest.mark.parametrize("size,accepted", [(32, True), (33, False)])
def test_real_http_response_enforces_exact_json_size_boundary(task, monkeypatch, size, accepted):
    monkeypatch.setattr(receipts, "MAX_JSON_BYTES", 32)
    body = b"[]" + b" " * (size - 2)
    calls = install_pages(monkeypatch, [lambda request: memory_http_response(
        request, body, {"Content-Length": size}
    )])
    if accepted:
        assert receipts.fetch_authenticated_comments(task, "synthetic-test-token") == []
    else:
        with pytest.raises(HandoffError, match="^github_comments_unavailable$"):
            receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert len(calls) == 1


@pytest.mark.parametrize("headers", [
    [("Content-Length", "2"), ("Content-Length", "2")],
    [("Content-Length", "2"), ("Content-Length", "999")],
    [("Content-Length", "2"), ("Transfer-Encoding", "chunked")],
    [("Content-Length", "2,2")], [("Content-Length", "+2")],
    [("Content-Length", "-2")], [("Content-Length", "")],
])
def test_ambiguous_or_invalid_http_content_length_fails_closed(task, monkeypatch, headers):
    calls = install_pages(monkeypatch, [lambda request: memory_http_response(request, b"[]", headers)])
    with pytest.raises(HandoffError, match="^github_comments_unavailable$"):
        receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert len(calls) == 1


@pytest.mark.parametrize("headers", [
    [("Transfer-Encoding", "gzip")],
    [("Transfer-Encoding", "gzip"), ("Transfer-Encoding", "chunked")],
    [("Transfer-Encoding", "chunked"), ("Transfer-Encoding", "gzip")],
    [("Transfer-Encoding", "chunked"), ("Transfer-Encoding", "chunked")],
    [("Transfer-Encoding", "gzip, chunked")],
    [("Transfer-Encoding", "chunked, gzip")],
    [("Transfer-Encoding", "chunked,chunked")],
    [("Transfer-Encoding", "chunked ")],
    [("Transfer-Encoding", "chunked\t")],
])
def test_unsupported_or_ambiguous_transfer_encoding_rejects_complete_raw_json(task, monkeypatch, headers):
    # In particular, http.client does not decode a "chunked " value as chunks.
    # Accepting that value after stripping whitespace would trust raw JSON that
    # never had the required HTTP chunk framing.
    calls = install_pages(monkeypatch, [lambda request: memory_http_response(request, b"[]", headers)])
    with pytest.raises(HandoffError, match="^github_comments_unavailable$"):
        receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert len(calls) == 1


@pytest.mark.parametrize("total", [0, 99, 100, 999, 1000, 1001])
def test_pagination_exhaustion_and_1000_comment_boundary(task, monkeypatch, total):
    comments = [{"id": n} for n in range(total)]
    pages = [comments[start:start + 100] for start in range(0, total, 100)]
    if total % 100 == 0:
        pages.append([])
    calls = install_pages(monkeypatch, pages)
    if total > 1000:
        with pytest.raises(HandoffError, match="comment_pagination_limit"):
            receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    else:
        assert receipts.fetch_authenticated_comments(task, "synthetic-test-token") == comments
    assert len(calls) == min(total // 100 + 1, 11)
    assert all(timeout == 15 for _, timeout in calls)
    assert [r.full_url.rsplit("=", 1)[-1] for r, _ in calls] == [
        str(n) for n in range(1, len(calls) + 1)
    ]


@pytest.mark.parametrize("bad_token", [None, "", "with space", "line\nbreak", "\x7f", "ä", "x" * 4097])
def test_invalid_token_never_constructs_transport(task, monkeypatch, bad_token):
    def forbidden(*args):
        pytest.fail("transport created before validation")
    monkeypatch.setattr(receipts, "build_opener", forbidden)
    with pytest.raises(HandoffError, match="GITHUB_TOKEN_required"):
        receipts.fetch_authenticated_comments(task, bad_token)


@pytest.mark.parametrize("repository", [
    "owner/../user", "owner/.", "owner/..", "../repo", "./repo", "owner/repo?query=yes",
    "owner/repo#fragment", "owner/repo/../../user", "https://evil.example/repo",
])
def test_network_boundary_rejects_path_query_injection(task, monkeypatch, repository):
    task["repository"] = repository
    def forbidden(*args):
        pytest.fail("transport created before task validation")
    monkeypatch.setattr(receipts, "build_opener", forbidden)
    with pytest.raises(HandoffError, match="invalid_repository"):
        receipts.fetch_authenticated_comments(task, "synthetic-test-token")


@pytest.mark.parametrize("failure", [
    HTTPError("https://api.github.com/private-token", 401, "private-token", {}, None),
    HTTPError("https://api.github.com/private-token", 429, "private-token", {}, None),
    URLError("private-token"), TimeoutError("private-token"),
    OSError("private-token"), BadStatusLine("private-token"),
    IncompleteRead(b"private-token", 50),
])
def test_network_failures_are_sanitized_and_never_retried(task, monkeypatch, failure):
    calls = install_pages(monkeypatch, [failure])
    with pytest.raises(HandoffError, match="^github_comments_unavailable$") as error:
        receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert "private-token" not in str(error.value)
    assert len(calls) == 1


def test_later_page_error_never_returns_partial_receipts(task, monkeypatch, tmp_path, capsys):
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task), encoding="utf-8")
    first_page = [acknowledgement(task)] + [{"id": n} for n in range(99)]
    calls = install_pages(monkeypatch, [first_page, BadStatusLine("SYNTHETIC_SECRET")])
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-test-token")
    assert receipts.main(["--task", str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ki-box-receipts: receipt_audit_failed\n"
    assert len(calls) == 2


@pytest.mark.parametrize("response", [
    b'{"unexpected":"root"}', b'[{"id":1,"id":2}]', b'[{"x":NaN}]',
    b'\xff', b'{',
])
def test_invalid_remote_json_fails_closed(task, monkeypatch, response):
    calls = install_pages(monkeypatch, [response])
    with pytest.raises(HandoffError):
        receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert len(calls) == 1


def test_deeply_nested_remote_list_cannot_create_ack(task, monkeypatch):
    install_pages(monkeypatch, [b'[' * 2000 + b']' * 2000])
    # Python decoders differ in nesting support; rejection or inert data is safe.
    try:
        comments = receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    except HandoffError:
        return
    assert status(task, comments) == "AWAITING_ACK"


@pytest.mark.parametrize("bad_response", [
    lambda request: MemoryResponse(b"[]", "https://other.example/comments"),
    lambda request: MemoryResponse(b"[]", request.full_url, status=202),
])
def test_wrong_response_binding_or_non200_fails_closed(task, monkeypatch, bad_response):
    calls = install_pages(monkeypatch, [bad_response])
    with pytest.raises(HandoffError, match="github_comments_unavailable"):
        receipts.fetch_authenticated_comments(task, "synthetic-test-token")
    assert len(calls) == 1


def test_oversized_response_is_bounded(task, monkeypatch):
    monkeypatch.setattr(receipts, "MAX_JSON_BYTES", 32)
    class BoundedResponse(MemoryResponse):
        def read(self, size=-1):
            assert size == 33, "remote read must have a fixed upper bound"
            return super().read(size)
    install_pages(monkeypatch, [lambda request: BoundedResponse(b" " * 33, request.full_url)])
    with pytest.raises(HandoffError, match="github_comments_unavailable"):
        receipts.fetch_authenticated_comments(task, "synthetic-test-token")


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("target", ["https://collector.example/leak", "http://api.github.com/leak"])
def test_real_urllib_redirect_flow_never_forwards_token(task, monkeypatch, code, target):
    """Exercise urllib's real error processor + redirect handler without sockets."""
    sent = []

    class RedirectTransport(HTTPSHandler, HTTPHandler):
        def response(self, request):
            sent.append((request.full_url, request.get_header("Authorization")))
            headers = Message()
            headers["Location"] = target
            result = addinfourl(io.BytesIO(b""), headers, request.full_url, code)
            result.msg = "Redirect"
            return result

        https_open = response
        http_open = response

    real_build_opener = build_opener
    monkeypatch.setattr(receipts, "build_opener", lambda *handlers: real_build_opener(
        *handlers, RedirectTransport()
    ))
    with pytest.raises(HandoffError, match="github_comments_unavailable"):
        receipts.fetch_authenticated_comments(task, "synthetic-secret-token")
    assert len(sent) == 1
    assert sent[0][0].startswith("https://api.github.com/repos/")
    assert sent[0][1] == "Bearer synthetic-secret-token"


@pytest.mark.parametrize("duplicate", ["repository", "thread_number", "recipients", "nested_id"])
def test_duplicate_task_keys_rejected_before_network(task, monkeypatch, tmp_path, capsys, duplicate):
    body = json.dumps(task)
    if duplicate == "nested_id":
        body = body.replace('"id": 199175422', '"id": 199175422, "id": 199175422')
    else:
        body = body[:-1] + "," + json.dumps(duplicate) + ":" + json.dumps(task[duplicate]) + "}"
    path = tmp_path / "task.json"
    path.write_text(body, encoding="utf-8")
    def forbidden(*args):
        pytest.fail("network invoked on duplicate-key task")
    monkeypatch.setattr(receipts, "fetch_authenticated_comments", forbidden)
    assert receipts.main(["--task", str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ki-box-receipts: receipt_audit_failed\n"


@pytest.mark.parametrize("body", ["{", "[]", "null", "[" * 2000 + "]" * 2000, '{"x":NaN}'])
def test_malformed_task_json_is_sanitized(task, monkeypatch, tmp_path, capsys, body):
    path = tmp_path / "task.json"
    path.write_text(body, encoding="utf-8")
    def forbidden(*args):
        pytest.fail("network invoked on malformed task")
    monkeypatch.setattr(receipts, "fetch_authenticated_comments", forbidden)
    assert receipts.main(["--task", str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ki-box-receipts: receipt_audit_failed\n"


def test_task_size_limit_rejects_valid_object_with_excess_padding(task, monkeypatch, tmp_path, capsys):
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task) + " " * 65537, encoding="utf-8")
    def forbidden(*args):
        pytest.fail("network invoked on oversized task")
    monkeypatch.setattr(receipts, "fetch_authenticated_comments", forbidden)
    assert receipts.main(["--task", str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ki-box-receipts: receipt_audit_failed\n"


def test_local_path_and_protocol_secrets_never_reach_cli(task, monkeypatch, tmp_path, capsys):
    assert receipts.main(["--task", str(tmp_path / "PRIVATE_SYNTHETIC_SECRET")]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err == "ki-box-receipts: receipt_audit_failed\n"
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task), encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-secret-token")
    install_pages(monkeypatch, [IncompleteRead(b"PRIVATE_SYNTHETIC_SECRET", 99)])
    assert receipts.main(["--task", str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err == "ki-box-receipts: receipt_audit_failed\n"


@pytest.mark.parametrize("arguments", [
    ["--unknown", "SYNTHETIC_ARGUMENT_SECRET"],
    ["--task", "task.json", "--unknown", "SYNTHETIC_ARGUMENT_SECRET"],
    ["--task", "--SYNTHETIC_ARGUMENT_SECRET"],
])
def test_invalid_cli_arguments_never_echo_untrusted_secret(capsys, arguments):
    assert receipts.main(arguments) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ki-box-receipts: receipt_audit_failed\n"


def test_main_reports_actual_authenticated_receipt_without_remote_body(task, monkeypatch, tmp_path, capsys):
    path = tmp_path / "task.json"
    path.write_text(json.dumps(task), encoding="utf-8")
    comment = acknowledgement(task)
    payload = json.loads(comment["body"])
    payload["private_extra"] = "SYNTHETIC_REMOTE_SECRET"
    comment["body"] = json.dumps(payload)
    install_pages(monkeypatch, [[comment]])
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-secret-token")
    assert receipts.main(["--task", str(path)]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["providers"]["copilot"]["status"] == "ACKNOWLEDGED"
    assert "SYNTHETIC_REMOTE_SECRET" not in output.out
    assert "synthetic-secret-token" not in output.out
