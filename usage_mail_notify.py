"""24/7 ALDI usage-mail monitor with no authenticated portal automation.

The monitor reads unread mailbox messages in read-only mode, recognizes only
sanitized 80%-used / consumed signals, and durably deduplicates each message via
an HMAC fingerprint on the repository state branch. It never logs message text,
sender, subject, Message-ID, phone number, credentials, or account data and never
starts an ALDI login or booking workflow.
"""

import email
import imaplib
import json
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path

from github_hardening_state import claim_trigger_key
from usage_mail_bridge import _mailboxes, _message_key, _signal


REPORT_PATH = os.getenv("ALDI_MAIL_NOTIFY_REPORT", "aldi-usage-alert.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _poll_one(index, host, port, user, password, claim=claim_trigger_key):
    alerts = []
    context = ssl.create_default_context()
    with imaplib.IMAP4_SSL(host, port, ssl_context=context) as client:
        client.login(user, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError(f"mailbox_{index}_select_failed")
        status, data = client.search(None, "UNSEEN")
        if status != "OK" or not data:
            return alerts

        for message_num in data[0].split()[-50:]:
            status, fetched = client.fetch(message_num, "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                continue
            raw = next((item[1] for item in fetched
                        if isinstance(item, tuple)
                        and isinstance(item[1], (bytes, bytearray))), None)
            if raw is None:
                continue
            raw = bytes(raw)
            message = email.message_from_bytes(raw)
            signal = _signal(message)
            if signal is None:
                continue
            if claim(_message_key(message, raw)):
                alerts.append({"mailbox": index, "signal": signal})
    return alerts


def _write(report):
    path = Path(REPORT_PATH)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main():
    report = {
        "started_at": _now(),
        "finished_at": None,
        "configured_mailboxes": 0,
        "configuration_error": None,
        "new_alerts": 0,
        "alerts": [],
        "failed_mailboxes": [],
        "authenticated_portal": False,
        "provider_action": False,
    }
    try:
        mailboxes = _mailboxes()
        report["configured_mailboxes"] = len(mailboxes)
        if not mailboxes:
            report["configuration_error"] = "no_mailboxes_configured"
            return 2
        for config in mailboxes:
            try:
                report["alerts"].extend(_poll_one(*config))
            except Exception as exc:
                report["failed_mailboxes"].append({
                    "mailbox": config[0],
                    "error": type(exc).__name__,
                })
        report["new_alerts"] = len(report["alerts"])
        return 2 if report["failed_mailboxes"] and not report["alerts"] else 0
    finally:
        report["finished_at"] = _now()
        _write(report)
        print(json.dumps({
            "configured_mailboxes": report["configured_mailboxes"],
            "configuration_error": report["configuration_error"],
            "new_alerts": report["new_alerts"],
            "failed_mailboxes": len(report["failed_mailboxes"]),
            "authenticated_portal": False,
            "provider_action": False,
        }), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
