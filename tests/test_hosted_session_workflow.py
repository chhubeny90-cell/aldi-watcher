"""Regression checks for disabled ALDI provider workflows; no provider access."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github/workflows/hosted-session.yml",
    ROOT / ".github/workflows/free-refill.yml",
    ROOT / ".github/workflows/http-login.yml",
)


def _text(path):
    return path.read_text(encoding="utf-8")


def test_hosted_session_is_a_dispatch_only_blocked_guard():
    text = _text(WORKFLOWS[0])
    triggers = text.split("\npermissions:", 1)[0]
    assert "ALDI Session and Free Refill (disabled)" in text
    assert "workflow_dispatch:" in triggers
    for trigger in ("push:", "schedule:", "workflow_run:", "pull_request:"):
        assert trigger not in triggers
    assert "inputs:" not in triggers
    assert "permissions:\n  contents: none\n" in text
    assert "jobs:\n  blocked:" in text
    assert "exit 2" in text
    assert "ALDI provider automation is disabled" in text


def test_all_provider_workflows_are_disabled_without_credentials_or_runtime():
    for path in WORKFLOWS:
        text = _text(path)
        assert "(disabled)" in text
        assert "workflow_dispatch:" in text
        assert "permissions:\n  contents: none\n" in text
        assert "jobs:\n  blocked:" in text
        assert "exit 2" in text
        for forbidden in (
            "secrets.", "GITHUB_TOKEN:", "ALDI_USER:", "ALDI_PASS",
            "ALDI_STATE_ENCRYPTION_KEY", "actions/checkout",
            "setup-python", "setup-chrome", "aldi_hosted_runtime.py",
            "aldi_http_login_probe.py", "AUTO_BOOK_ENABLED",
        ):
            assert forbidden not in text


def test_blocked_provider_workflows_make_no_account_or_booking_request():
    for path in WORKFLOWS:
        text = _text(path)
        assert "kein ALDI-Kontakt" in text
        for action in ("Anmeldung", "Statusabfrage", "Buchung", "Wiederholung"):
            assert action in text
