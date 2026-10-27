"""Regression checks for the intentionally disabled hosted session workflow."""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/hosted-session.yml"


def test_hosted_session_is_explicitly_disabled_and_manual_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    triggers = text.split("\\non:", 1)[1].split("\\npermissions:", 1)[0]
    assert "workflow_dispatch:" in triggers
    assert "schedule:" not in triggers
    assert "workflow_run:" not in triggers
    assert "push:" not in triggers and "pull_request:" not in triggers
    assert "ALDI Session and Free Refill (disabled)" in text
    assert "permissions:\\n  contents: none\\n" in text
    assert "jobs:\\n  blocked:" in text


def test_disabled_hosted_session_has_no_secrets_or_provider_runtime():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text
    assert "ALDI_USER:" not in text
    assert "ALDI_PASS:" not in text
    assert "ALDI_STATE_ENCRYPTION_KEY:" not in text
    assert "aldi_hosted_runtime.py" not in text
    assert "no provider request was made" in text
