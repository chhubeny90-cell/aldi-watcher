from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_authenticated_account_workflow_remains_disabled():
    text = _workflow("accounts.yml")
    assert "ALDI Accounts (disabled)" in text
    assert "Authenticated ALDI account automation is disabled." in text
    assert "ALDI_ACCOUNTS_ENC" not in text
    assert "ALDI_PASS" not in text
    assert "Install Chrome" not in text


def test_mail_monitor_does_not_receive_provider_password():
    text = _workflow("mail-trigger.yml")

    assert "ALDI_RECOVERY_KEY: ${{ secrets.ALDI_RECOVERY_KEY }}" in text
    assert "ALDI_PASS: ${{ secrets.ALDI_PASS }}" not in text
    assert "ALDI_PASS_ENC: ${{ secrets.ALDI_PASS_ENC }}" not in text
    assert "ALDI_USER:" not in text
    assert "usage_mail_notify.py" in text
    assert "repository_dispatch" not in text


def test_main_workflow_has_no_authenticated_live_refill():
    text = _workflow("run.yml")

    assert "github_live_refill_http.py" not in text
    assert "github_live_refill.py" not in text
    assert "ALDI_MANUAL_AUTH_ONCE" not in text
    assert "ALDI_EXPECTED_ACCOUNT" not in text
    assert "ALDI_PASS:" not in text
    assert "AUTO_BOOK_ENABLED: 'false'" in text
    assert "portal_probe.py" in text


def test_policy_safe_24_7_workflow_cadence_is_preserved():
    assert "cron: '0 * * * *'" in _workflow("mail-trigger.yml")
    assert "cron: '7-59/15 * * * *'" in _workflow("run.yml")
    assert "schedule:" not in _workflow("watchdog.yml")
    assert "schedule:" not in _workflow("accounts.yml")


def test_24_7_active_workflows_use_node24_compatible_action_generations():
    for name in ("run.yml", "mail-trigger.yml"):
        text = _workflow(name)
        assert "actions/checkout@v4" not in text
        assert "actions/setup-python@v5" not in text
        assert "browser-actions/setup-chrome@v1" not in text
        assert "actions/upload-artifact@v4" not in text

    run = _workflow("run.yml")
    mail = _workflow("mail-trigger.yml")
    assert "actions/checkout@v7.0.1" in run
    assert "actions/setup-python@v7.0.0" in run
    assert "browser-actions/setup-chrome@v2.2.0" in run
    assert "actions/upload-artifact@v7.0.2" in run
    assert "actions/checkout@v7.0.1" in mail
    assert "actions/setup-python@v7.0.0" in mail
    assert "actions/upload-artifact@v7.0.2" in mail


def test_disabled_workflows_have_no_provider_credentials_or_browser_runtime():
    for name in ("accounts.yml", "status-probe.yml", "watchdog.yml"):
        text = _workflow(name)
        assert "ALDI_PASS" not in text
        assert "ALDI_USER" not in text
        assert "browser-actions/setup-chrome" not in text


def test_login_diagnostics_workflow_is_disabled_without_provider_access():
    text = _workflow("login-format.yml")
    assert "ALDI Login Format Diagnostics (disabled)" in text
    assert "  workflow_dispatch:" in text
    assert "  push:" not in text
    assert "permissions:\n  contents: none" in text
    assert "jobs:\n  blocked:" in text
    assert "ALDI provider automation is disabled" in text
    assert "python aldi_public_login_controls.py" not in text
    assert "secrets." not in text


def test_disabled_login_diagnostics_cannot_fan_out_into_provider_jobs():
    text = _workflow("login-format.yml")
    assert "inputs:" not in text
    assert "actions/checkout" not in text
    assert "setup-chrome" not in text
    assert "ALDI_PASS" not in text
    assert "ALDI_USER" not in text
    assert "github_live_refill" not in text
