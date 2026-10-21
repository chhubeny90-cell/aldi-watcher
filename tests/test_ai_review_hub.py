import json

import pytest

from tools.ai_review_hub import (
    COST_POLICY,
    ReviewError,
    ReviewTask,
    _load_json,
    aggregate_reviews,
    build_prompt,
    main,
    validate_review,
)


def test_prompt_masks_phone_and_email_but_accepts_them_as_private_input():
    prompt = build_prompt(
        ReviewTask(
            provider="openai",
            target_commit="842e120",
            question="Pruefe Profil +49 151 23456789",
            context="Mailbox user@example.com gehoert zu 0151/23456789",
        )
    )

    assert "+49 151 23456789" not in prompt
    assert "0151/23456789" not in prompt
    assert "user@example.com" not in prompt
    assert "<PHONE_REDACTED>" in prompt
    assert "<EMAIL_REDACTED>" in prompt


def test_prompt_declares_zero_cost_policy():
    prompt = build_prompt(
        ReviewTask(
            provider="gemini",
            target_commit="842e120",
            question="Review the state machine",
        )
    )

    assert COST_POLICY == "ZERO_COST_ONLY"
    assert "ZERO_COST_ONLY" in prompt
    assert "paid/metered API" in prompt


def test_external_review_cannot_echo_phone_number():
    with pytest.raises(ReviewError, match="private_identifier_in_external_output"):
        validate_review(
            {
                "provider": "copilot",
                "target_commit": "842e120",
                "summary": "Account 0151 23456789 looks correct",
                "claims": [],
            }
        )


def test_external_review_cannot_echo_mailbox_address():
    with pytest.raises(ReviewError, match="private_identifier_in_external_output"):
        validate_review(
            {
                "provider": "perplexity",
                "target_commit": "842e120",
                "summary": "Mailbox user@example.com is configured",
                "claims": [],
            }
        )


SECRET_LITERALS = [
    "github_pat_" + "a" * 70,
    "AIza" + "a" * 35,
    "pplx-" + "a" * 48,
    "aUtHoRiZaTiOn: Bearer synthetic-private-value",
    '"Proxy-Authorization": "Basic synthetic-private-value"',
    "cOoKiE: session=synthetic-private-value",
    "sEt-CoOkIe: session=synthetic-private-value; HttpOnly",
    '"api_key": "synthetic-private-value"',
    "GEMINI_API_KEY=synthetic-private-value",
    "password = synthetic-private-value",
    "ALDI_PASS='synthetic-private-value'",
    '"client_secret": "synthetic-private-value"',
    '"Authorization":\n "Bearer synthetic-private-value"',
    "password:\n  synthetic-private-value",
    '"api_key"\n:\n "synthetic-private-value"',
]


def review():
    return {
        "provider": "copilot",
        "target_commit": "a" * 40,
        "summary": "Offline review only",
        "claims": [{
            "category": "security/review",
            "claim": "Require independent receipt evidence",
            "evidence": ["tools/ki_box_receipts.py"],
            "proposed_change": "Check stable account IDs",
            "risk_if_wrong": "False receipt attribution",
            "confidence": "high",
        }],
    }


@pytest.mark.parametrize("secret", SECRET_LITERALS)
@pytest.mark.parametrize("field", ["question", "context"])
def test_prompt_refuses_provider_tokens_and_credential_literals(secret, field):
    fields = {"question": "Review public context", "context": ""}
    fields[field] = secret
    with pytest.raises(ReviewError, match="obvious_secret_detected"):
        build_prompt(ReviewTask("copilot", "a" * 40, **fields))


@pytest.mark.parametrize("secret", SECRET_LITERALS)
@pytest.mark.parametrize("field", ["summary", "claim", "evidence", "proposed_change", "risk_if_wrong"])
def test_review_publication_refuses_provider_tokens_and_credentials(secret, field):
    data = review()
    if field == "summary":
        data[field] = secret
    else:
        data["claims"][0][field] = [secret] if field == "evidence" else secret
    with pytest.raises(ReviewError, match="obvious_secret_detected"):
        validate_review(data)


def test_aggregation_cannot_bypass_review_publication_guard():
    data = review()
    data["claims"][0]["evidence"] = ["Cookie: synthetic-private-value"]
    with pytest.raises(ReviewError, match="obvious_secret_detected"):
        aggregate_reviews([data])


@pytest.mark.parametrize("data", [[], None, "untrusted", 42])
def test_nonobject_review_is_rejected_without_attribute_error(data):
    with pytest.raises(ReviewError, match="review_root_not_object"):
        validate_review(data)


@pytest.mark.parametrize("raw", [
    '{"provider":"gemini","provider":"copilot"}',
    '{"claims":[{"claim":"one","claim":"two"}]}',
])
def test_loader_rejects_duplicate_keys_at_every_depth(tmp_path, raw):
    path = tmp_path / "review.json"
    path.write_text(raw)
    with pytest.raises(ReviewError, match="duplicate_json_key"):
        _load_json(path)


@pytest.mark.parametrize("raw", ["{", "[]", '{"value":NaN}', '{"value":Infinity}'])
def test_loader_rejects_malformed_nonobject_or_nonstandard_json(tmp_path, raw):
    path = tmp_path / "review.json"
    path.write_text(raw)
    with pytest.raises(ReviewError):
        _load_json(path)


def test_parser_recursion_failure_is_sanitized_across_python_versions(tmp_path, monkeypatch):
    path = tmp_path / "review.json"
    path.write_text("{}")

    def failing_parser(*args, **kwargs):
        raise RecursionError("synthetic-private-value")

    monkeypatch.setattr("tools.ai_review_hub.json.load", failing_parser)
    with pytest.raises(ReviewError, match="^invalid_review_json$"):
        _load_json(path)


@pytest.mark.parametrize("secret", ["Authorization: Bearer synthetic-private-value",
                                  '"Authorization":\n "Bearer synthetic-private-value"',
                                  "password:\n  synthetic-private-value"])
@pytest.mark.parametrize("command", ["prepare", "validate", "aggregate"])
def test_cli_rejects_secret_publication_without_output(tmp_path, capsys, command, secret):
    marker = "synthetic-private-value"
    context = tmp_path / "context.txt"
    context.write_text(secret)
    path = tmp_path / "review.json"
    data = review()
    data["summary"] = secret
    path.write_text(json.dumps(data))
    args = {
        "prepare": ["prepare", "--provider", "copilot", "--commit", "a" * 40,
                    "--question", "Review", "--context-file", str(context)],
        "validate": ["validate", "--provider", "copilot", "--commit", "a" * 40,
                     "--input", str(path)],
        "aggregate": ["aggregate", str(path)],
    }[command]
    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ai-review-hub: operation_rejected\n"
    assert marker not in output.err


@pytest.mark.parametrize("failure", ["missing_path", "invalid_utf8", "invalid_json", "arguments"])
def test_cli_errors_never_echo_paths_values_or_raw_arguments(tmp_path, capsys, failure):
    marker = "synthetic-private-value"
    path = tmp_path / (marker + ".json")
    args = ["validate", "--provider", "copilot", "--commit", "a" * 40,
            "--input", str(path)]
    if failure == "invalid_utf8":
        path.write_bytes(b"\xff" + marker.encode())
    elif failure == "invalid_json":
        path.write_text('{"' + marker + '":')
    elif failure == "arguments":
        args = ["validate", "--provider", marker]
    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "ai-review-hub: operation_rejected\n"


def test_valid_offline_cli_review_and_aggregation_still_work(tmp_path, capsys):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review()))
    assert main(["validate", "--provider", "copilot", "--commit", "a" * 40,
                 "--input", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["provider"] == "copilot"
    assert main(["aggregate", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "HUMAN_OR_REPOSITORY_RECONCILIATION_REQUIRED"
    assert output["target_commit"] == "a" * 40
    assert output["providers"] == ["copilot"]
