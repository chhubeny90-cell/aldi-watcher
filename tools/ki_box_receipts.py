"""Read-only, zero-cost verification of AI handoff receipts on GitHub.

GitHub's authenticated comment author is evidence for that GitHub account only,
not cryptographic evidence of the upstream model. An owner-written handoff is
never proof of delivery to a different AI. No provider or ALDI API is called.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROVIDERS = ("copilot", "gemini", "perplexity", "openai")
SHA_RE = re.compile(r"[0-9a-f]{40}")
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}")
IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?")
CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
TASK_RE = re.compile(r"[A-Za-z0-9_-]{4,100}")
MAX_JSON_BYTES = 8 * 1024 * 1024


class HandoffError(ValueError):
    pass


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise HandoffError("invalid_arguments")


class _NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects before forwarding the GitHub bearer token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HandoffError("redirect_not_allowed")


def validate_task(task: dict) -> dict:
    if not isinstance(task, dict):
        raise HandoffError("task_must_be_object")
    for key, pattern in (
        ("repository", REPO_RE), ("commit", SHA_RE),
        ("challenge", CHALLENGE_RE), ("task_id", TASK_RE),
        ("sender_login", IDENTITY_RE),
    ):
        if not isinstance(task.get(key), str) or pattern.fullmatch(task[key]) is None:
            raise HandoffError("invalid_" + key)
    if task["repository"].split("/")[1] in (".", ".."):
        raise HandoffError("invalid_repository")
    if type(task.get("thread_number")) is not int or task["thread_number"] < 1:
        raise HandoffError("invalid_thread_number")
    if task.get("thread_kind") not in ("issues", "pull"):
        raise HandoffError("invalid_thread_kind")
    if type(task.get("sender_id")) is not int or task["sender_id"] < 1:
        raise HandoffError("invalid_sender_id")
    if not isinstance(task.get("recipients"), dict):
        raise HandoffError("invalid_recipients")
    if set(task["recipients"]) != set(PROVIDERS):
        raise HandoffError("recipients_must_identify_all_providers")
    logins = {task["sender_login"].casefold()}
    account_ids = {task["sender_id"]}
    for provider, recipient in task["recipients"].items():
        if recipient is None:
            continue
        if (not isinstance(recipient, dict) or set(recipient) != {"login", "id"}
                or not isinstance(recipient.get("login"), str)
                or IDENTITY_RE.fullmatch(recipient["login"]) is None
                or type(recipient.get("id")) is not int or recipient["id"] < 1
                or recipient["login"].casefold() in logins
                or recipient["id"] in account_ids):
            raise HandoffError("invalid_recipient_identity:" + provider)
        logins.add(recipient["login"].casefold())
        account_ids.add(recipient["id"])
    return task


def _load_unique_json(body):
    """One strict parser for tasks, REST responses and receipt envelopes."""
    def no_duplicate_keys(pairs):
        out = {}
        for key, val in pairs:
            if key in out:
                raise HandoffError("duplicate_json_key")
            out[key] = val
        return out

    def no_nonfinite_numbers(value):
        raise HandoffError("nonfinite_json_number")

    try:
        return json.loads(body, object_pairs_hook=no_duplicate_keys,
                          parse_constant=no_nonfinite_numbers)
    except (ValueError, TypeError, RecursionError) as exc:
        raise HandoffError("invalid_json") from exc


def _parse_unique_json(body: str) -> dict | None:
    if not isinstance(body, str) or len(body) > 8192:
        return None
    try:
        obj = _load_unique_json(body)
    except HandoffError:
        return None
    return obj if isinstance(obj, dict) else None


def assess_receipts(task: dict, comments: list[dict]) -> dict:
    """Comments MUST be obtained from authenticated GitHub REST by the caller.

    Supplying a hand-crafted list is suitable for offline tests only. An ACK
    proves a matching GitHub account posted a matching envelope in that thread;
    it does not prove that Gemini/Perplexity received the prompt upstream.
    """
    validate_task(task)
    if not isinstance(comments, list):
        raise HandoffError("comments_must_be_list")
    statuses = {}
    thread_segment = task["thread_kind"]
    for provider, recipient in task["recipients"].items():
        status = {"status": "NOT_CONNECTED" if recipient is None else "AWAITING_ACK"}
        if recipient is None:
            statuses[provider] = status
            continue
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            author = comment.get("user")
            if (not isinstance(author, dict) or not isinstance(author.get("login"), str)
                    or author["login"].casefold() != recipient["login"].casefold()
                    or type(author.get("id")) is not int or author["id"] != recipient["id"]):
                continue
            url = comment.get("html_url")
            # Validate exact GitHub thread and a nonzero issuecomment anchor.
            expected_prefix = (
                f"https://github.com/{task['repository']}/"
                f"{thread_segment}/{task['thread_number']}#issuecomment-"
            )
            comment_id = comment.get("id")
            if (type(comment_id) is not int or comment_id < 1
                    or url != expected_prefix + str(comment_id)):
                continue
            payload = _parse_unique_json(comment.get("body"))
            if payload is None or payload.get("type") != "KI_ACK_V1":
                continue
            if any(payload.get(k) != task[k] for k in ("task_id", "commit", "challenge")):
                continue
            if payload.get("provider") != provider or payload.get("owner") != task["sender_login"]:
                continue
            status = {"status": "ACKNOWLEDGED", "receipt_url": url,
                      "review_status": "PENDING", "completion_status": "OPEN"}
            break
        statuses[provider] = status
    return {
        "task_id": task["task_id"], "commit": task["commit"],
        "repository": task["repository"], "thread_kind": task["thread_kind"],
        "thread_number": task["thread_number"],
        "status": "RECEIPT_AUDIT_ONLY", "providers": statuses,
        "aldi_live_status": "BLOCKED", "external_model_execution": "NOT_PROVEN",
    }


def fetch_authenticated_comments(task: dict, token: str) -> list[dict]:
    # Validate at the network boundary, including callers other than main().
    validate_task(task)
    if (not isinstance(token, str) or not token or len(token) > 4096
            or not token.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in token)):
        raise HandoffError("GITHUB_TOKEN_required")
    # Only the validated canonical GitHub API host is queried.
    repo = task["repository"]
    number = task["thread_number"]
    comments: list[dict] = []
    opener = build_opener(_NoRedirectHandler)
    # Page 11 is only an exhaustion probe: at most 1,000 comments are accepted.
    for page in range(1, 12):
        url = f"https://api.github.com/repos/{repo}/issues/{number}/comments?per_page=100&page={page}"
        req = Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "aldi-watcher-ki-box-receipts",
        })
        try:
            with opener.open(req, timeout=15) as response:
                if response.url != url or response.status != 200:
                    raise HandoffError("unexpected_api_url")
                lengths = response.headers.get_all("Content-Length", [])
                encodings = response.headers.get_all("Transfer-Encoding", [])
                if (len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings)
                        # Match http.client's decoder selection exactly.
                        or (encodings and encodings[0].lower() != "chunked")):
                    raise HandoffError("ambiguous_response_length")
                expected_length = None
                if lengths:
                    raw_length = lengths[0].strip()
                    if re.fullmatch(r"[0-9]{1,16}", raw_length) is None:
                        raise HandoffError("invalid_response_length")
                    expected_length = int(raw_length)
                    if expected_length > MAX_JSON_BYTES:
                        raise HandoffError("github_response_too_large")
                body = response.read(MAX_JSON_BYTES + 1)
                if len(body) > MAX_JSON_BYTES:
                    raise HandoffError("github_response_too_large")
                # HTTPResponse.read(amt) may silently return short valid JSON.
                # A bounded read must still satisfy the declared HTTP framing.
                if expected_length is not None and len(body) != expected_length:
                    raise HandoffError("incomplete_github_response")
                page_data = _load_unique_json(body)
        except (HTTPError, URLError, OSError, HTTPException, ValueError) as exc:
            raise HandoffError("github_comments_unavailable") from exc
        if not isinstance(page_data, list) or len(page_data) > 100:
            raise HandoffError("github_comments_invalid_response")
        if page == 11:
            if page_data:
                raise HandoffError("comment_pagination_limit")
            break
        comments.extend(page_data)
        if len(page_data) < 100:
            break
    return comments


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(prog="ki-box-receipts", description=__doc__)
    parser.add_argument("--task", required=True, help="path to public task JSON")
    try:
        args = parser.parse_args(argv)
        with open(args.task, encoding="utf-8") as handle:
            body = handle.read(65537)
            if len(body) > 65536:
                raise HandoffError("task_too_large")
            task = validate_task(_load_unique_json(body))
        comments = fetch_authenticated_comments(task, os.environ.get("GITHUB_TOKEN", ""))
        print(json.dumps(assess_receipts(task, comments), sort_keys=True, indent=2))
        return 0
    except (OSError, HTTPException, ValueError):
        # Arbitrary OS/JSON/protocol exception text may contain paths or secrets.
        print("ki-box-receipts: receipt_audit_failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
