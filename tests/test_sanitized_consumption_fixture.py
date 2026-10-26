"""Offline regression for the sanitized 26 Oct ALDI consumption-mail sample."""
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

import imaplib

import usage_mail_bridge as bridge
import usage_mail_notify as notify


FIXTURE = Path(__file__).parent / "fixtures" / "consumed_email_2026-10-26.eml"


def test_sanitized_consumption_message_is_only_a_consumed_signal():
    message = BytesParser(policy=policy.default).parsebytes(FIXTURE.read_bytes())

    assert bridge._signal(message) == "consumed"
    serialized = FIXTURE.read_text(encoding="utf-8")
    assert "pokemonpuschel" not in serialized.casefold()
    assert "christoph" not in serialized.casefold()
    assert "0163" not in serialized
    assert "example.invalid" in serialized


def test_probe_reports_sanitized_imap_login_stage_without_server_text(monkeypatch):
    class LoginRejected:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def login(self, *_args):
            raise imaplib.IMAP4.error("PRIVATE_SERVER_RESPONSE")

    monkeypatch.setattr(notify.imaplib, "IMAP4_SSL", LoginRejected)
    result = notify._probe_one(
        1, "imap.example.invalid", 993, "private-user", "private-password"
    )

    assert result["error"] == "IMAPError"
    assert result["error_stage"] == "login"
    rendered = json.dumps(result)
    assert "PRIVATE_SERVER_RESPONSE" not in rendered
    assert "private-user" not in rendered
    assert "private-password" not in rendered


def test_workflow_surfaces_only_the_sanitized_probe_stage():
    workflow = Path(".github/workflows/mail-trigger.yml").read_text(encoding="utf-8")

    assert "diagnostic.get('error_stage')" in workflow
    assert "diagnostic.get('error')" in workflow
    assert "PRIVATE_SERVER_RESPONSE" not in workflow
