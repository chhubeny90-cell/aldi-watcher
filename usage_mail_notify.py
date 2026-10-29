"""24/7 ALDI usage-mail monitor with no authenticated portal automation.

The monitor reads a bounded recent UID window in read-only mode, recognizes
sanitized warning / consumed / confirmation signals, and deduplicates each message via
an HMAC fingerprint on the repository state branch. It never logs message text,
sender, subject, Message-ID, phone number, credentials, or account data and never
starts an ALDI login or booking workflow.

Observed mailbox behavior is intentionally reflected here: an 80% message is a
heads-up only; a consumed-volume message is the actionable refill notification.
"""

import email
import base64
import hashlib
import hmac
import imaplib
import json
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path

from github_hardening_state import claim_trigger_key
from core.mail_handoff_queue import enqueue_consumed, _legacy_seen
from core import iphone_notification_outbox
import core.mail_handoff_queue as handoff_queue
from usage_mail_bridge import (_mailboxes, _message_key, _legacy_message_key,
                               _signal)
from core.mailbox_cursor import MailboxCursor


REPORT_PATH = os.getenv("ALDI_MAIL_NOTIFY_REPORT", "aldi-usage-alert.json")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _configure_dedup_key():
    """Use a dedicated key or derive a stable, separately labelled mail key."""
    if os.environ.get("ALDI_RECOVERY_KEY", "").strip():
        return "dedicated"
    encoded = os.environ.get("ALDI_STATE_ENCRYPTION_KEY", "").strip()
    if not encoded:
        return "missing"
    try:
        raw = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
        if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii") != encoded:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ValueError("state_dedup_key_invalid") from None
    os.environ["ALDI_RECOVERY_KEY"] = hmac.new(
        raw, b"aldi-mail-dedup-key-v1", hashlib.sha256).hexdigest()
    return "state_key"


def _trigger_policy():
    policy = os.environ.get("ALDI_MAIL_TRIGGER_POLICY", "consumed_only").strip()
    if policy not in {"consumed_only", "portal_check"}:
        raise ValueError("trigger_policy_invalid")
    return policy


def _notification_seen(message_key, legacy_message_key):
    """Preserve all retained per-message history when switching notification paths."""
    if _legacy_seen(message_key, legacy_message_key):
        return True
    _, events = handoff_queue._load()
    _, archived = handoff_queue._archive()
    aliases = {handoff_queue._fingerprint(key) for key in (message_key, legacy_message_key)}
    return bool(aliases.intersection(events) or aliases.intersection(archived))


def _poll_one(index, host, port, user, password, claim=claim_trigger_key,
              enqueue=enqueue_consumed, scan_reports=None):
    alerts = []
    policy = _trigger_policy()
    context = ssl.create_default_context()
    with imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=20) as client:
        client.login(user, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError(f"mailbox_{index}_select_failed")
        cursor = MailboxCursor(host, user, client)
        uids = cursor.batch()
        for message_num in uids:
            status, fetched = client.uid("fetch", message_num, "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                raise RuntimeError("mailbox_uid_fetch_failed")
            raw = next((item[1] for item in fetched
                        if isinstance(item, tuple)
                        and isinstance(item[1], (bytes, bytearray))), None)
            if raw is None:
                raise RuntimeError("mailbox_uid_message_missing")
            raw = bytes(raw)
            message = email.message_from_bytes(raw)
            signal = _signal(message)
            if signal is None:
                continue
            message_key = _message_key(message, raw)
            if signal == "consumed" and os.getenv("ALDI_IPHONE_NOTIFY_ENABLED", "").lower() == "true":
                # Explicit iPhone opt-in takes precedence over legacy trigger
                # policy. Record durably before UID progress even if the policy
                # was omitted and defaults to consumed_only.
                is_new = (
                    not _notification_seen(message_key, _legacy_message_key(message, raw))
                    and iphone_notification_outbox.enqueue(message_key)
                )
            elif signal == "consumed" and policy == "consumed_only":
                # Reserve the actionable event durably before reporting it.
                # No provider action is dispatched from this monitor.
                is_new = enqueue(message_key, signal,
                                 legacy_message_key=_legacy_message_key(message, raw))
            elif signal == "consumed":
                is_new = (
                    not _notification_seen(message_key, _legacy_message_key(message, raw))
                    and claim(message_key)
                )
            else:
                # Preserve retained legacy fingerprints before claiming a v2
                # warning/confirmation, just as for consumed mail. History failures abort.
                is_new = (not _legacy_seen(
                    message_key, _legacy_message_key(message, raw)
                ) and claim(message_key))
            if is_new:
                alerts.append({
                    "mailbox": index,
                    "signal": signal,
                    "actionable": signal == "consumed",
                })
        # Cursor progress follows all classification and durable dedup writes.
        # A crash before this CAS replays mail through the immutable identities.
        cursor.commit()
        if scan_reports is not None:
            scan_reports.append({"mailbox": index, "processed_messages": len(uids),
                                 "pending_messages": cursor.backlog,
                                 "uidvalidity_changed": cursor.validity_changed})
    return alerts


def _mailbox_error(exc):
    """Use fixed classes; server text and custom exception names stay private."""
    if isinstance(exc, imaplib.IMAP4.error):
        return "IMAPError"
    if isinstance(exc, TimeoutError):
        return "TimeoutError"
    if isinstance(exc, ssl.SSLError):
        return "TLSError"
    if isinstance(exc, OSError):
        return "ConnectionError"
    return "MailboxError"


def _probe_one(index, host, port, user, password):
    """Verify IMAP login and readonly INBOX without message or durable-state access."""
    result = {"mailbox": index, "login_ok": False, "readonly_inbox_ok": False,
              "message_processing": False, "error": None}
    try:
        with imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=20) as client:
            status, _ = client.login(user, password)
            if status != "OK":
                raise imaplib.IMAP4.error("login_failed")
            result["login_ok"] = True
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise imaplib.IMAP4.error("readonly_select_failed")
            result["readonly_inbox_ok"] = True
    except Exception as exc:
        result["error"] = _mailbox_error(exc)
    return result


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
        "dedup_key_configured": False,
        "dedup_key_source": "missing",
        "connection_only": os.getenv("ALDI_MAIL_CONNECTION_ONLY", "").strip().lower() == "true",
        "configuration_error": None,
        "new_alerts": 0,
        "actionable_alerts": 0,
        "early_warnings": 0,
        "refill_confirmations": 0,
        "option_confirmations": 0,
        "order_notifications": 0,
        "mailbox_connectivity": [],
        "mailbox_scans": [],
        "alerts": [],
        "failed_mailboxes": [],
        "authenticated_portal": False,
        "provider_action": False,
        "booking_authorized": False,
        "provider_check_requested": False,
        "trigger_policy": "consumed_only",
    }
    try:
        try:
            report["trigger_policy"] = _trigger_policy()
            report["dedup_key_source"] = _configure_dedup_key()
        except ValueError as exc:
            report["configuration_error"] = str(exc)
            return 2
        try:
            mailboxes = _mailboxes()
        except (RuntimeError, ValueError) as exc:
            # A partial configuration must produce the same sanitized report as
            # an empty one. Never persist arbitrary exception text: it may
            # contain a configured port or other private input.
            known_errors = {
                "mailbox_1_configuration_incomplete",
                "mailbox_2_configuration_incomplete",
            }
            error = str(exc)
            report["configuration_error"] = (
                error if error in known_errors else "mailbox_configuration_invalid"
            )
            return 2
        report["configured_mailboxes"] = len(mailboxes)
        report["dedup_key_configured"] = bool(os.environ.get("ALDI_RECOVERY_KEY", "").strip())
        if not mailboxes:
            report["configuration_error"] = "no_mailboxes_configured"
            return 2
        if not report["dedup_key_configured"] or report["connection_only"]:
            if not report["dedup_key_configured"]:
                report["configuration_error"] = "dedup_key_missing"
            for config in mailboxes:
                result = _probe_one(*config)
                report["mailbox_connectivity"].append(result)
                if result["error"] is not None:
                    report["failed_mailboxes"].append({"mailbox": config[0], "error": result["error"]})
            return 2 if report["configuration_error"] or report["failed_mailboxes"] else 0
        for config in mailboxes:
            try:
                report["alerts"].extend(_poll_one(*config, scan_reports=report["mailbox_scans"]))
            except Exception as exc:
                report["failed_mailboxes"].append({
                    "mailbox": config[0],
                    "error": _mailbox_error(exc),
                })
        report["new_alerts"] = len(report["alerts"])
        report["actionable_alerts"] = sum(
            1 for item in report["alerts"] if item.get("actionable") is True
        )
        report["early_warnings"] = sum(
            1 for item in report["alerts"] if item.get("signal") == "80_percent"
        )
        for field, signal in (("refill_confirmations", "refill_confirmation"),
                              ("option_confirmations", "option_confirmation"),
                              ("order_notifications", "order_received")):
            report[field] = sum(item.get("signal") == signal for item in report["alerts"])
        report["provider_check_requested"] = (
            report["trigger_policy"] == "portal_check"
            and report["actionable_alerts"] > 0
            and os.getenv("ALDI_IPHONE_NOTIFY_ENABLED", "").lower() != "true")
        return 2 if report["failed_mailboxes"] and not report["alerts"] else 0
    finally:
        report["finished_at"] = _now()
        _write(report)
        print(json.dumps({
            "configured_mailboxes": report["configured_mailboxes"],
            "dedup_key_configured": report["dedup_key_configured"],
            "dedup_key_source": report["dedup_key_source"],
            "connection_only": report["connection_only"],
            "configuration_error": report["configuration_error"],
            "new_alerts": report["new_alerts"],
            "actionable_alerts": report["actionable_alerts"],
            "early_warnings": report["early_warnings"],
            "refill_confirmations": report["refill_confirmations"],
            "option_confirmations": report["option_confirmations"],
            "order_notifications": report["order_notifications"],
            "mailbox_connectivity": report["mailbox_connectivity"],
            "mailbox_scans": report["mailbox_scans"],
            "failed_mailboxes": len(report["failed_mailboxes"]),
            "trigger_policy": report["trigger_policy"],
            "authenticated_portal": False,
            "provider_action": False,
            "booking_authorized": False,
            "provider_check_requested": report["provider_check_requested"],
        }), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
