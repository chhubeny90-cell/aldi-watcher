"""Regression tests for presence-only mailbox diagnostics."""

from pathlib import Path

from scripts import mail_secret_preflight as preflight


def test_empty_mailbox_secrets_show_missing_without_credential_values(capsys):
    assert preflight.main({}) == 0
    out = capsys.readouterr().out
    assert "MAILBOX_2_HOST: missing" in out
    assert "MAILBOX_2_USER: missing" in out
    assert "MAILBOX_2_PASS: missing" in out
    assert "does not prove" not in out
    assert "Cause cannot be determined" in out


def test_mailbox_diagnostics_never_log_secret_values_or_lengths(capsys):
    env = {
        "MAILBOX_2_HOST": "imap.test.invalid",
        "MAILBOX_2_USER": "highly-private-mailbox-name@example.invalid",
        "MAILBOX_2_PASS": "VERY_PRIVATE_LONG_TEST_PASSWORD_VALUE",
    }
    assert preflight.check_presence(env) == {
        "MAILBOX_2_HOST": True,
        "MAILBOX_2_USER": True,
        "MAILBOX_2_PASS": True,
    }
    assert preflight.main(env) == 0
    out = capsys.readouterr().out
    assert "MAILBOX_2_USER: set" in out
    assert "MAILBOX_2_PASS: set" in out
    assert "does not prove successful IMAP authentication" in out
    for value in env.values():
        assert value not in out
        assert str(len(value)) not in out


def test_partial_mailbox_still_warns_and_preserves_fail_closed_monitor(capsys):
    assert preflight.main({
        "MAILBOX_2_USER": "user@example.invalid",
        "MAILBOX_2_PASS": "",
        "MAILBOX_2_HOST": "imap.gmail.com",
    }) == 0
    out = capsys.readouterr().out
    assert "MAILBOX_2_USER: set" in out
    assert "MAILBOX_2_PASS: missing" in out
    assert "::warning" in out

    workflow = Path(".github/workflows/mail-trigger.yml").read_text(encoding="utf-8")
    assert "python scripts/mail_secret_preflight.py\n          python usage_mail_notify.py" in workflow
    assert "continue-on-error: true" in workflow
    assert "Surface refill-ready mail or mailbox failure" in workflow
    assert "AUTO_BOOK_ENABLED: 'false'" in workflow
    assert "ALDI_MAIL_TRIGGER_POLICY: notify_only" in workflow
