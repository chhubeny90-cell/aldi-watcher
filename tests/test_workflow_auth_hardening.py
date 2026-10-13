from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_accounts_workflow_checks_backoff_before_account_secrets():
    text = _workflow("accounts.yml")
    guard = text.index("Check durable provider auth guard")
    secret = text.index("ALDI_ACCOUNTS_ENC: ${{ secrets.ALDI_ACCOUNTS_ENC }}")
    chrome = text.index("Install Chrome")

    assert guard < secret
    assert guard < chrome
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in text
    assert "ALDI_STATE_PATH: .aldi-state/profile-1.json" in text
    assert "_auth_guard_status" in text


def test_mail_trigger_does_not_receive_provider_password():
    text = _workflow("mail-trigger.yml")

    assert "ALDI_RECOVERY_KEY: ${{ secrets.ALDI_RECOVERY_KEY }}" in text
    assert "ALDI_PASS: ${{ secrets.ALDI_PASS }}" not in text
    assert "ALDI_PASS_ENC: ${{ secrets.ALDI_PASS_ENC }}" not in text


def test_live_refill_uses_verified_http_auth_handoff():
    text = _workflow("run.yml")

    assert "timeout 180s python github_live_refill_http.py" in text
    assert "timeout 180s python github_live_refill.py" not in text


def test_24_7_workflow_cadence_is_preserved():
    assert "cron: '*/5 * * * *'" in _workflow("mail-trigger.yml")
    assert "cron: '3-59/10 * * * *'" in _workflow("run.yml")
    assert "cron: '7,22,37,52 * * * *'" in _workflow("watchdog.yml")
    assert "cron: '17 * * * *'" in _workflow("accounts.yml")


def test_24_7_chain_uses_node24_compatible_action_generations():
    for name in ("run.yml", "mail-trigger.yml", "watchdog.yml", "accounts.yml"):
        text = _workflow(name)
        assert "actions/checkout@v4" not in text
        assert "actions/setup-python@v5" not in text
        assert "browser-actions/setup-chrome@v1" not in text
        assert "actions/upload-artifact@v4" not in text

    assert "actions/checkout@v7.0.1" in _workflow("run.yml")
    assert "actions/setup-python@v7.0.0" in _workflow("run.yml")
    assert "browser-actions/setup-chrome@v2.2.0" in _workflow("run.yml")
    assert "actions/upload-artifact@v7.0.2" in _workflow("run.yml")
