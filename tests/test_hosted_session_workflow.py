"""Static safety checks for owner-gated manual and scheduled ALDI sessions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hosted-session.yml"


def _text():
    return WORKFLOW.read_text(encoding="utf-8")


def _triggers():
    return _text().split("\non:", 1)[1].split("\npermissions:", 1)[0]


def test_only_manual_and_hourly_cron_trigger_provider_workflow():
    triggers = _triggers()
    assert "workflow_dispatch:" in triggers
    assert "schedule:" in triggers
    assert "cron: '21 * * * *'" in triggers
    for forbidden in ("\n  workflow_run:", "\n  repository_dispatch:", "\n  push:", "\n  pull_request:"):
        assert forbidden not in triggers
    assert "github.ref == 'refs/heads/main'" in _text()
    assert "github.run_attempt == 1" in _text()
    assert "cancel-in-progress: false" in _text()


def test_dispatch_cannot_select_unattended_mode_and_owner_input_is_default_false():
    triggers = _triggers()
    for mode in ("preflight", "initialize", "observe", "refill"):
        assert "          - " + mode in triggers
    assert "          - automatic" not in triggers
    assert "default: preflight" in triggers
    assert "confirm_provider_authorization:" in triggers
    assert "default: false" in triggers


def test_cron_needs_durable_owner_provider_and_booking_approvals():
    text = _text()
    preflight = text.split("\n  preflight:\n", 1)[1].split("\n  session:\n", 1)[0]
    session = text.split("\n  session:\n", 1)[1]
    assert "RUN_MODE: ${{ github.event_name == 'schedule' && 'automatic' || inputs.mode }}" in preflight
    assert "OWNER_CONFIRMED: ${{ github.event_name == 'schedule' && vars.ALDI_OWNER_AUTO_REFILL_APPROVED == 'true' || inputs.confirm_provider_authorization == true }}" in preflight
    assert "BOOKING_APPROVED: ${{ vars.ALDI_LIVE_REFILL_APPROVED == 'true' }}" in preflight
    assert 'not booking or yes("TARGET_SUFFIX_PRESENT")' in preflight
    assert "needs.preflight.outputs.ready == 'true'" in session
    assert "vars.ALDI_SCRIPT_ACCESS_APPROVED == 'true'" in session
    assert "vars.ALDI_PROVIDER_APPROVAL_REFERENCE != ''" in session
    assert "vars.ALDI_OWNER_AUTO_REFILL_APPROVED == 'true'" in session
    assert "vars.ALDI_LIVE_REFILL_APPROVED == 'true'" in session
    assert "inputs.confirm_provider_authorization == true" in session
    assert "environment: ${{ github.event_name == 'schedule' && 'aldi-auto' || 'aldi-session' }}" in session


def test_booking_env_requires_explicit_flag_and_is_limited_to_one():
    text = _text()
    session = text.split("\n  session:\n", 1)[1]
    assert "AUTO_BOOK_ENABLED: ${{ (github.event_name == 'schedule' || inputs.mode == 'refill') && 'true' || 'false' }}" in session
    assert "DRY_RUN: ${{ (github.event_name == 'schedule' || inputs.mode == 'refill') && 'false' || 'true' }}" in session
    assert "ALDI_MAX_REFILLS_PER_RUN: '1'" in session
    assert "ALDI_HOSTED_MODE: ${{ github.event_name == 'schedule' && 'automatic' || inputs.mode }}" in session
    assert "ALDI_REQUIRED_TARGET_SUFFIX: ${{ secrets.ALDI_REQUIRED_TARGET_SUFFIX }}" in session


def test_live_runner_retains_strict_free_price_journal_cooldown_and_completion():
    live = (ROOT / "aldi_live_refill.py").read_text(encoding="utf-8")
    contract = (ROOT / "aldi_live_refill_contract.py").read_text(encoding="utf-8")
    hosted = (ROOT / "aldi_hosted_runtime.py").read_text(encoding="utf-8")
    assert "and evidence.get('free_evidence') == 'explicit_free_offer'" in live
    assert "if not _explicit_zero_price_offer(evidence):" in live
    assert "if not _explicit_zero_price_offer(current_evidence)" in live
    assert "recent_success_guard_seconds=0 if same_run_success else 30" in live
    assert "if _unresolved_aldi(db, account):" in live
    assert "contract.main()" in hosted
    assert "state.save_journal(self.db_path)" in hosted
    assert "_persist_provider_evidence" in contract


def test_secrets_step_scoped_without_public_artifacts():
    text = _text()
    preflight = text.split("\n  preflight:\n", 1)[1].split("\n  session:\n", 1)[0]
    session = text.split("\n  session:\n", 1)[1]
    assert "permissions:\n  contents: none" in text
    assert "aldi_hosted_runtime.py" not in preflight
    assert "browser-actions/setup-chrome" not in preflight
    assert "ALDI_PASS: ${{ secrets.ALDI_PASS }}" not in preflight
    assert "    permissions:\n      contents: write" in session
    assert "persist-credentials: false" in session
    assert "ALDI_STATE_ENCRYPTION_KEY: ${{ secrets.ALDI_STATE_ENCRYPTION_KEY }}" in session
    assert "ALDI_PASS: ${{ secrets.ALDI_PASS }}" in session
    assert "GITHUB_TOKEN: ${{ github.token }}" in session
    assert "actions/upload-artifact" not in text
    assert "python aldi_hosted_runtime.py --summary-only" in session
