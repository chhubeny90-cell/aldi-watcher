"""Static safety checks for the opt-in hosted ALDI session workflow."""
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/hosted-session.yml"


def _text():
    return WORKFLOW.read_text(encoding="utf-8")


def test_hosted_session_runs_only_by_explicit_manual_dispatch():
    text = _text()
    triggers = text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "workflow_dispatch:" in triggers
    for forbidden in ("schedule:", "workflow_run:", "repository_dispatch:", "push:", "pull_request:"):
        assert forbidden not in triggers
    assert "default: preflight" in triggers
    assert "confirm_provider_authorization:" in triggers
    assert "default: false" in triggers


def test_live_booking_and_automatic_modes_remain_unreachable():
    text = _text()
    triggers = text.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "          - initialize" in triggers
    assert "          - observe" in triggers
    assert "          - refill" not in triggers
    assert "          - automatic" not in triggers
    assert "AUTO_BOOK_ENABLED: 'false'" in text
    assert "AUTO_BOOK_ENABLED: 'true'" not in text
    assert "DRY_RUN: 'true'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "github.run_attempt == 1" in text


def test_runtime_is_fail_closed_on_provider_authorization_and_environment():
    text = _text()
    session = text.split("\n  session:\n", 1)[1]
    assert "needs.preflight.outputs.ready == 'true'" in session
    assert "inputs.confirm_provider_authorization == true" in session
    assert "vars.ALDI_SCRIPT_ACCESS_APPROVED == 'true'" in session
    assert "vars.ALDI_PROVIDER_APPROVAL_REFERENCE != ''" in session
    assert "environment: aldi-session" in session
    assert "    permissions:\n      contents: write" in session


def test_preflight_cannot_read_credentials_or_contact_provider():
    text = _text()
    preflight = text.split("\n  preflight:\n", 1)[1].split("\n  session:\n", 1)[0]
    assert "permissions:\n  contents: none" in text
    assert "ALDI_PASS: ${{ secrets.ALDI_PASS }}" not in preflight
    assert "ALDI_USER: ${{ secrets.ALDI_PROFILE_1_USER }}" not in preflight
    assert "aldi_hosted_runtime.py" not in preflight
    assert "browser-actions/setup-chrome" not in preflight
    assert "Check only configuration presence (no provider request)" in preflight


def test_session_secrets_are_step_scoped_and_not_published():
    text = _text()
    session = text.split("\n  session:\n", 1)[1]
    assert "persist-credentials: false" in session
    assert "ALDI_STATE_ENCRYPTION_KEY: ${{ secrets.ALDI_STATE_ENCRYPTION_KEY }}" in session
    assert "ALDI_PASS: ${{ secrets.ALDI_PASS }}" in session
    assert "GITHUB_TOKEN: ${{ github.token }}" in session
    assert "actions/upload-artifact" not in text
    assert "python aldi_hosted_runtime.py --summary-only" in session
