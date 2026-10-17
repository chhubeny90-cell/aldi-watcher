import pytest

from tools.ai_review_hub import (
    COST_POLICY,
    ReviewError,
    ReviewTask,
    build_prompt,
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
