"""Create and email a short-lived refill activation link after a consumed-volume alert.

This module never logs credentials, recipient addresses, phone numbers or tokens. It only
issues a signed opaque token for an external activation endpoint. The endpoint must enforce
single use; this repository intentionally does not automate the ALDI customer portal.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit


REPORT_PATH = Path(os.getenv("ALDI_MAIL_NOTIFY_REPORT", "aldi-usage-alert.json"))
TOKEN_TTL_SECONDS = max(60, min(3600, int(os.getenv("ALDI_LINK_TTL_SECONDS", "900"))))
PROFILE = os.getenv("ALDI_PROFILE_ID", "profile-1").strip() or "profile-1"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name.lower()}_missing")
    return value


def _recipients() -> list[str]:
    raw = _required("ALDI_REFILL_RECIPIENTS")
    values = [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]
    if not values or len(values) > 20:
        raise RuntimeError("invalid_recipient_count")
    if any("@" not in value or "\n" in value or "\r" in value for value in values):
        raise RuntimeError("invalid_recipient")
    return values


def _activation_base() -> str:
    value = _required("ALDI_ACTIVATION_BASE_URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError("invalid_activation_base_url")
    if parsed.fragment:
        raise RuntimeError("activation_base_url_must_not_have_fragment")
    return value


def _read_actionable_count() -> int:
    if not REPORT_PATH.is_file():
        raise RuntimeError("usage_report_missing")
    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    value = payload.get("actionable_alerts", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError("invalid_actionable_alert_count")
    return value


def _token(now: int | None = None) -> str:
    key = _required("ALDI_LINK_SIGNING_KEY").encode("utf-8")
    if len(key) < 32:
        raise RuntimeError("link_signing_key_too_short")
    issued = int(time.time() if now is None else now)
    payload = {
        "v": 1,
        "profile": PROFILE,
        "iat": issued,
        "exp": issued + TOKEN_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(18),
        "action": "request_refill",
    }
    encoded = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64url(hmac.new(key, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def _message(link: str, recipients: list[str]) -> EmailMessage:
    sender = _required("ALDI_NOTIFY_FROM")
    if "@" not in sender or "\n" in sender or "\r" in sender:
        raise RuntimeError("invalid_notify_from")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"ALDI REFILL {PROFILE}"
    msg.set_content(
        "ALDI TALK hat gemeldet, dass das Datenvolumen verbraucht ist.\n\n"
        "Aktivierungslink (kurzlebig):\n"
        f"{link}\n\n"
        "Der Link enthaelt keine ALDI-Zugangsdaten. Er ist fuer genau diesen Refill-Vorgang gedacht.\n"
    )
    return msg


def _send(msg: EmailMessage) -> None:
    host = _required("ALDI_NOTIFY_SMTP_HOST")
    port = int(os.getenv("ALDI_NOTIFY_SMTP_PORT", "465"))
    user = _required("ALDI_NOTIFY_SMTP_USER")
    password = _required("ALDI_NOTIFY_SMTP_PASS")
    if port not in range(1, 65536):
        raise RuntimeError("invalid_smtp_port")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as client:
        client.login(user, password)
        client.send_message(msg)


def main() -> int:
    actionable = _read_actionable_count()
    if actionable == 0:
        print(json.dumps({"sent": False, "reason": "no_actionable_alert"}), flush=True)
        return 0

    recipients = _recipients()
    token = _token()
    link = _activation_base() + "#" + token
    _send(_message(link, recipients))
    print(json.dumps({
        "sent": True,
        "profile": PROFILE,
        "recipient_count": len(recipients),
        "ttl_seconds": TOKEN_TTL_SECONDS,
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
