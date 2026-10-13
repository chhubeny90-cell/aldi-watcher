from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_accounts_workflow_checks_backoff_before_account_secrets():
    text = (ROOT / ".github" / "workflows" / "accounts.yml").read_text(encoding="utf-8")
    guard = text.index("Check durable provider auth guard")
    secret = text.index("ALDI_ACCOUNTS_ENC: ${{ secrets.ALDI_ACCOUNTS_ENC }}")
    chrome = text.index("Install Chrome")

    assert guard < secret
    assert guard < chrome
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in text
    assert "ALDI_STATE_PATH: .aldi-state/profile-1.json" in text
    assert "_auth_guard_status" in text


def test_mail_trigger_does_not_receive_provider_password():
    text = (ROOT / ".github" / "workflows" / "mail-trigger.yml").read_text(encoding="utf-8")

    assert "ALDI_RECOVERY_KEY: ${{ secrets.ALDI_RECOVERY_KEY }}" in text
    assert "ALDI_PASS: ${{ secrets.ALDI_PASS }}" not in text
    assert "ALDI_PASS_ENC: ${{ secrets.ALDI_PASS_ENC }}" not in text
