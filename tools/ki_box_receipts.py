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
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROVIDERS = ("copilot", "gemini", "perplexity", "openai")
SHA_RE = re.compile(r"[0-9a-f]{40}")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?")
CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
TASK_RE = re.compile(r"[A-Za-z0-9_-]{4,100}")


class HandoffError(ValueError):
    pass


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
    if type(task.get("thread_number")) is not int or task["thread_number"] < 1:
        raise HandoffError("invalid_thread_number")
    if task.get("thread_kind") not in ("issues", "pull"):
        raise HandoffError("invalid_thread_kind")
    if not isinstance(task.get("recipients"), dict):
        raise HandoffError("invalid_recipients")
    if set(task["recipients"]) != set(PROVIDERS):
        raise HandoffError("recipients_must_identify_all_providers")
    for provider, expected_author in task["recipients"].items():
        if expected_author is not None and (
            not isinstance(expected_author, str)
            or IDENTITY_RE.fullmatch(expected_author) is None
            or expected_author.casefold() == task["sender_login"].casefold()
        ):
            raise HandoffError("invalid_recipient_identity:" + provider)
    return task


def _parse_unique_json(body: str) -> dict | None:
    if not isinstance(body, str) or len(body) > 8192:
        return None

    def no_duplicate_keys(pairs):
        out = {}
        for key, val in pairs:
            if key in out:
                raise ValueError("duplicate_json_key")
            out[key] = val
        return out

    try:
        obj = json.loads(body, object_pairs_hook=no_duplicate_keys)
    except (ValueError, TypeError):
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
    for provider, expected_author in task["recipients"].items():
        status = {"status": "NOT_CONNECTED" if expected_author is None else "AWAITING_ACK"}
        if expected_author is None:
            statuses[provider] = status
            continue
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            author = comment.get("user")
            if not isinstance(author, dict) or author.get("login") != expected_author:
                continue
            url = comment.get("html_url")
            # Validate exact GitHub thread and a nonzero issuecomment anchor.
            expected_prefix = (
                f"https://github.com/{task['repository']}/"
                f"{thread_segment}/{task['thread_number']}#issuecomment-"
            )
            if not isinstance(url, str) or not re.fullmatch(
                re.escape(expected_prefix) + r"[1-9][0-9]*", url
            ):
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
    if not token:
        raise HandoffError("GITHUB_TOKEN_required")
    # Only the validated canonical GitHub API host is queried.
    repo = task["repository"]
    number = task["thread_number"]
    comments: list[dict] = []
    for page in range(1, 11):
        url = f"https://api.github.com/repos/{repo}/issues/{number}/comments?per_page=100&page={page}"
        req = Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "aldi-watcher-ki-box-receipts",
        })
        try:
            with build_opener(_NoRedirectHandler).open(req, timeout=15) as response:
                if response.url != url:
                    raise HandoffError("unexpected_api_url")
                page_data = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise HandoffError("github_comments_unavailable") from exc
        if not isinstance(page_data, list):
            raise HandoffError("github_comments_invalid_response")
        comments.extend(page_data)
        if len(page_data) < 100:
            break
    else:
        raise HandoffError("comment_pagination_limit")
    return comments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="path to public task JSON")
    args = parser.parse_args(argv)
    try:
        with open(args.task, encoding="utf-8") as handle:
            task = validate_task(json.load(handle))
        comments = fetch_authenticated_comments(task, os.environ.get("GITHUB_TOKEN", ""))
        print(json.dumps(assess_receipts(task, comments), sort_keys=True, indent=2))
        return 0
    except (HandoffError, OSError, ValueError) as exc:
        # Do not print credential or remote comment bodies.
        print("ki-box-receipts: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
