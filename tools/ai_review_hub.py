#!/usr/bin/env python3
"""API-neutral review hub for cross-checking external AI reviews.

The first version intentionally does not call provider APIs. It builds provider-specific
review prompts and validates/aggregates JSON responses that were returned manually or
by a future adapter. No provider response may directly change runtime behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

PROVIDERS = ("perplexity", "gemini", "copilot", "openai")
COST_POLICY = "ZERO_COST_ONLY"
CATEGORIES = (
    "research/provider",
    "architecture/state-machine",
    "security/review",
    "code/test",
    "operations/deployment",
    "duplicate/stale",
)
CONFIDENCE = ("low", "medium", "high")

ROLE_FOCUS = {
    "perplexity": (
        "Prioritize current public evidence: official provider documentation, public portal "
        "behavior, endpoint evidence, dates, and source quality. Clearly separate verified "
        "facts from inference. Do not claim repository state unless supplied in the context."
    ),
    "gemini": (
        "Act as an independent architecture and threat-model reviewer. Focus on state-machine "
        "correctness, failure modes, trust boundaries, idempotency, and safer alternatives."
    ),
    "copilot": (
        "Act as a repository/code reviewer. Focus on concrete defects, race conditions, tests, "
        "CI/workflow weaknesses, Python correctness, and minimal patches. Do not invent external "
        "provider facts."
    ),
    "openai": (
        "Reconcile architecture, implementation, security, and operations. Challenge assumptions, "
        "prefer fail-closed behavior, and identify which claims need repository or live evidence."
    ),
}

OBVIOUS_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bpplx-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"\b(?:authorization|proxy-authorization|cookie|set-cookie)\b"
        r"[\"']?\s*:\s*(?:\"[^\"\r\n]+\"|'[^'\r\n]+'|[^\s\"'<>]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:[a-z0-9]+_)*(?:api[_-]?key|password|passwd|pass|client[_-]?secret|"
        r"(?:access|refresh)[_-]?token)\b[\"']?\s*[:=]\s*"
        r"(?:\"[^\"\r\n]+\"|'[^'\r\n]+'|[^\s\"'<>]+)",
        re.IGNORECASE,
    ),
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
GERMAN_MOBILE_PATTERN = re.compile(
    r"(?<!\w)(?:\+49|0049|0)[\s()/.-]*1[5-7]\d(?:[\s()/.-]*\d){7,9}(?!\w)"
)


class ReviewError(ValueError):
    pass


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's default error includes raw arguments, which may be secrets.
        raise ReviewError("invalid_arguments")


@dataclass(frozen=True)
class ReviewTask:
    provider: str
    target_commit: str
    question: str
    context: str = ""


def _reject_obvious_secrets(text: str) -> None:
    # Defense in depth only: callers must supply public, reviewed context.
    # Arbitrary passwords cannot be recognized by their content alone.
    for pattern in OBVIOUS_SECRET_PATTERNS:
        if pattern.search(text):
            raise ReviewError("obvious_secret_detected")


def _sanitize_external_text(text: str) -> str:
    """Mask operational identifiers before context leaves the private workflow."""
    text = EMAIL_PATTERN.sub("<EMAIL_REDACTED>", text)
    text = GERMAN_MOBILE_PATTERN.sub("<PHONE_REDACTED>", text)
    return text


def _reject_external_private_identifiers(text: str) -> None:
    if EMAIL_PATTERN.search(text) or GERMAN_MOBILE_PATTERN.search(text):
        raise ReviewError("private_identifier_in_external_output")


def build_prompt(task: ReviewTask) -> str:
    if task.provider not in PROVIDERS:
        raise ReviewError("unsupported_provider")
    if not isinstance(task.target_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{7,40}", task.target_commit):
        raise ReviewError("invalid_target_commit")
    if not isinstance(task.question, str) or not isinstance(task.context, str):
        raise ReviewError("invalid_task_text")
    _reject_obvious_secrets(task.question)
    _reject_obvious_secrets(task.context)

    question = _sanitize_external_text(task.question)
    context = _sanitize_external_text(task.context)

    return f"""You are one reviewer in a multi-model GitHub review hub.

Target repository commit: {task.target_commit}
Provider role: {task.provider}
Role focus: {ROLE_FOCUS[task.provider]}
Cost policy: {COST_POLICY}. Do not recommend or initiate paid/metered API usage.

Task:
{question.strip()}

Repository/context supplied to you:
{context.strip() or '(none)'}

Hard rules:
- Review ONLY the target commit/context supplied. If evidence is missing, say so.
- Phone numbers and mailbox addresses may have been masked before this prompt was created; do not reconstruct or request them.
- Never output credentials, tokens, passwords, phone numbers, mailbox addresses, cookies, or private provider identifiers.
- Treat external AI/model consensus as non-authoritative.
- Do not weaken fail-closed behavior merely to make the system more convenient.
- Do not claim a live provider action happened unless explicit evidence proves it.
- Return JSON only, no Markdown fences and no prose outside the JSON.

Required JSON shape:
{{
  "provider": "{task.provider}",
  "target_commit": "{task.target_commit}",
  "summary": "short review summary",
  "claims": [
    {{
      "category": "one of: {', '.join(CATEGORIES)}",
      "claim": "one concrete finding",
      "evidence": ["repo path/line, test name, public URL, or explicit missing-evidence note"],
      "proposed_change": "specific change or 'none'",
      "risk_if_wrong": "short consequence",
      "confidence": "low|medium|high"
    }}
  ]
}}
"""


def _normalize_space(value: str) -> str:
    return " ".join(value.strip().split())


def _claim_fingerprint(category: str, claim: str) -> str:
    normalized = f"{category}\n{_normalize_space(claim).lower()}".encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:16]


def validate_review(data: dict[str, Any], expected_provider: str | None = None,
                    expected_commit: str | None = None) -> dict[str, Any]:
    """Validate untrusted review content; this does not authenticate a provider."""
    if not isinstance(data, dict):
        raise ReviewError("review_root_not_object")
    provider = data.get("provider")
    target_commit = data.get("target_commit")
    summary = data.get("summary")
    claims = data.get("claims")

    if provider not in PROVIDERS:
        raise ReviewError("invalid_provider")
    if expected_provider and provider != expected_provider:
        raise ReviewError("provider_mismatch")
    if not isinstance(target_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{7,40}", target_commit):
        raise ReviewError("invalid_target_commit")
    if expected_commit and target_commit.lower() != expected_commit.lower():
        raise ReviewError("commit_mismatch")
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewError("invalid_summary")
    if not isinstance(claims, list):
        raise ReviewError("invalid_claims")

    _reject_obvious_secrets(summary)
    _reject_external_private_identifiers(summary)
    normalized_claims: list[dict[str, Any]] = []
    for idx, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ReviewError(f"claim_{idx}_not_object")
        category = claim.get("category")
        text = claim.get("claim")
        evidence = claim.get("evidence")
        proposed_change = claim.get("proposed_change")
        risk_if_wrong = claim.get("risk_if_wrong")
        confidence = claim.get("confidence")
        if category not in CATEGORIES:
            raise ReviewError(f"claim_{idx}_invalid_category")
        if not isinstance(text, str) or not text.strip():
            raise ReviewError(f"claim_{idx}_invalid_text")
        if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
            raise ReviewError(f"claim_{idx}_invalid_evidence")
        if not isinstance(proposed_change, str) or not isinstance(risk_if_wrong, str):
            raise ReviewError(f"claim_{idx}_invalid_change_or_risk")
        if confidence not in CONFIDENCE:
            raise ReviewError(f"claim_{idx}_invalid_confidence")
        combined = "\n".join([text, *evidence, proposed_change, risk_if_wrong])
        _reject_obvious_secrets(combined)
        _reject_external_private_identifiers(combined)
        normalized_claims.append({
            "id": _claim_fingerprint(category, text),
            "category": category,
            "claim": _normalize_space(text),
            "evidence": [_normalize_space(item) for item in evidence],
            "proposed_change": _normalize_space(proposed_change),
            "risk_if_wrong": _normalize_space(risk_if_wrong),
            "confidence": confidence,
        })

    return {
        "provider": provider,
        "target_commit": target_commit.lower(),
        "summary": _normalize_space(summary),
        "claims": normalized_claims,
    }


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def aggregate_reviews(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    if not reviews:
        raise ReviewError("no_reviews")
    # Keep the public aggregation helper behind the same publication checks.
    reviews = [validate_review(review) for review in reviews]
    commits = {review["target_commit"] for review in reviews}
    if len(commits) != 1:
        raise ReviewError("mixed_target_commits")

    flattened: list[dict[str, Any]] = []
    for review in reviews:
        for claim in review["claims"]:
            flattened.append({**claim, "provider": review["provider"]})

    duplicate_groups: list[dict[str, Any]] = []
    seen: set[int] = set()
    for i, left in enumerate(flattened):
        if i in seen:
            continue
        group = [i]
        for j in range(i + 1, len(flattened)):
            right = flattened[j]
            if right["category"] != left["category"]:
                continue
            if _similarity(left["claim"], right["claim"]) >= 0.88:
                group.append(j)
        if len(group) > 1:
            seen.update(group)
            duplicate_groups.append({
                "category": left["category"],
                "providers": sorted({flattened[n]["provider"] for n in group}),
                "claim_ids": [flattened[n]["id"] for n in group],
            })

    potential_conflicts: list[dict[str, Any]] = []
    for i, left in enumerate(flattened):
        for right in flattened[i + 1:]:
            if left["provider"] == right["provider"] or left["category"] != right["category"]:
                continue
            claim_similarity = _similarity(left["claim"], right["claim"])
            change_similarity = _similarity(left["proposed_change"], right["proposed_change"])
            if claim_similarity >= 0.60 and change_similarity < 0.45:
                potential_conflicts.append({
                    "category": left["category"],
                    "providers": [left["provider"], right["provider"]],
                    "claim_ids": [left["id"], right["id"]],
                    "reason": "similar finding but materially different proposed changes",
                })

    return {
        "target_commit": next(iter(commits)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_policy": COST_POLICY,
        "providers": sorted({review["provider"] for review in reviews}),
        "claims": flattened,
        "duplicate_groups": duplicate_groups,
        "potential_conflicts": potential_conflicts,
        "decision": "HUMAN_OR_REPOSITORY_RECONCILIATION_REQUIRED",
    }


def _load_json(path: Path) -> dict[str, Any]:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReviewError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ReviewError("invalid_json_constant")

    with path.open("r", encoding="utf-8") as handle:
        try:
            data = json.load(handle, object_pairs_hook=unique_object,
                             parse_constant=invalid_constant)
        except ReviewError:
            raise
        except (ValueError, RecursionError) as exc:
            raise ReviewError("invalid_review_json") from exc
    if not isinstance(data, dict):
        raise ReviewError("review_root_not_object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(prog="ai-review-hub", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="build a provider-specific prompt")
    prepare.add_argument("--provider", choices=PROVIDERS, required=True)
    prepare.add_argument("--commit", required=True)
    prepare.add_argument("--question", required=True)
    prepare.add_argument("--context-file", type=Path)

    validate = sub.add_parser("validate", help="validate one provider JSON response")
    validate.add_argument("--provider", choices=PROVIDERS, required=True)
    validate.add_argument("--commit", required=True)
    validate.add_argument("--input", type=Path, required=True)

    aggregate = sub.add_parser("aggregate", help="aggregate validated provider responses")
    aggregate.add_argument("inputs", nargs="+", type=Path)

    try:
        args = parser.parse_args(argv)
        if args.command == "prepare":
            context = args.context_file.read_text(encoding="utf-8") if args.context_file else ""
            print(build_prompt(ReviewTask(args.provider, args.commit, args.question, context)))
            return 0
        if args.command == "validate":
            data = _load_json(args.input)
            print(json.dumps(validate_review(data, args.provider, args.commit), indent=2, ensure_ascii=False))
            return 0
        reviews = [validate_review(_load_json(path)) for path in args.inputs]
        print(json.dumps(aggregate_reviews(reviews), indent=2, ensure_ascii=False))
        return 0
    except (ReviewError, OSError, ValueError, TypeError, RecursionError):
        # Never publish paths, arbitrary exception details, or raw arguments.
        print("ai-review-hub: operation_rejected", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
