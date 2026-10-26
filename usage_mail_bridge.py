"""Poll up to two IMAP inboxes for ALDI usage alerts and wake the live runner.

Matched mail is never modified or marked read. Message identifiers are reduced to
SHA-256 keys before they leave this process. The live runner performs durable
HMAC deduplication before any provider login.
"""

import email
import hashlib
import hmac
import imaplib
import json
import os
import re
import ssl
from email.header import decode_header, make_header
from email.utils import getaddresses
from html.parser import HTMLParser
from urllib.parse import quote

import requests
from core.mailbox_cursor import MailboxCursor

try:
    from github_hardening_state import _mac, _trigger_state
except Exception:
    _mac = None
    _trigger_state = None


ALDI_SENDER_DOMAINS = {"alditalk-kundenbetreuung.de"}


class _VisibleHTML(HTMLParser):
    """Read visible text without retaining links, scripts or style contents."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "div", "br", "tr", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "tr", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _body_text(message):
    parts = []
    def visible_parts(part):
        if part.get_content_disposition() == "attachment" or part.get_content_type() == "message/rfc822":
            return
        if part.is_multipart():
            for child in part.get_payload():
                yield from visible_parts(child)
        else:
            yield part

    for part in visible_parts(message):
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)):
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        text = text[:50000]
        if part.get_content_type() == "text/html":
            parser = _VisibleHTML()
            parser.feed(text)
            text = "".join(parser.parts)
        parts.append(text)
    return "\n".join(parts)[:100000]


def _signal(message):
    """Classify notifications, never prove identity, eligibility or completion.

    The observed provider templates use the same subject for warnings and
    consumption. Authentication-Results is not a trusted actor authorization:
    its presence or absence cannot turn this classifier into booking proof.
    """
    senders = getaddresses([_decode(message.get("From"))])
    if len(senders) != 1:
        return None
    local, separator, domain = senders[0][1].rpartition("@")
    if not separator or not local or domain.casefold() not in ALDI_SENDER_DOMAINS:
        return None
    subject = " ".join(_decode(message.get("Subject")).casefold().split())
    if re.match(r"^(?:re|aw|fw|fwd|wg)\s*:", subject):
        return None
    text = " ".join(_body_text(message).casefold().split())
    combined = subject + " " + text
    if re.search(r"bestell|buchung|nachbuch|zusatz.option", subject):
        provisioned = re.search(
            r"(?:erfolgreich\s+(?:aktiviert|(?:nach)?gebucht)|"
            r"(?:wurde|ist)\s+(?:erfolgreich\s+)?(?:aktiviert|(?:nach)?gebucht))", text)
        if re.search(r"\bnicht\s+(?:erfolgreich\s+)?(?:aktiviert|(?:nach)?gebucht)", text):
            return None
        if provisioned:
            # Generic add-on confirmations do not identify a free 1-GB refill.
            if (re.search(r"\b1\s*gb\b", text)
                    and re.search(r"kostenlos|gratis|0[,.]00\s*(?:€|eur)", text)):
                return "refill_confirmation"
            return "option_confirmation"
        if re.search(r"bestellung\s+(?:erhalten|eingegangen)|bestellung.*war erfolgreich", text):
            return "order_received"
        return None
    if not re.search(r"daten\s*volumen|high.?speed", subject):
        return None
    if re.search(r"\b80\s*(?:%|prozent)", combined) and re.search(r"daten|volumen|high.?speed|verbrauch", combined):
        return "80_percent"
    if re.search(r"(?:daten\s*volumen|high.?speed(?:.volumen)?)[^.!?]{0,100}\b(?:ist\s+(?:nun\s+)?(?:vollständig\s+)?|vollständig\s+)(?:verbraucht|aufgebraucht)\b", text):
        return "consumed"
    return None


def _message_key(message, raw_bytes):
    key = os.environ.get("ALDI_RECOVERY_KEY", "").strip()
    if not key:
        raise RuntimeError("recovery_key_unavailable")
    # Length-delimited JSON avoids ambiguous concatenation. Missing headers
    # use the stable raw digest, never a mailbox UID or receive timestamp.
    material = json.dumps([
        "mail-identity-v2", (message.get("Message-ID") or "").strip(),
        (message.get("Date") or "").strip(),
        "" if message.get("Message-ID") else hashlib.sha256(raw_bytes).hexdigest(),
    ], separators=(",", ":"), ensure_ascii=True).encode()
    return hmac.new(key.encode(), material, hashlib.sha256).hexdigest()


def _legacy_message_key(message, raw_bytes):
    message_id = (message.get("Message-ID") or "").strip()
    material = message_id.encode("utf-8", errors="ignore") if message_id else raw_bytes
    return hashlib.sha256(material).hexdigest()


def _already_seen(message_key):
    if _mac is None or _trigger_state is None:
        raise RuntimeError("deduplication_unavailable")
    _, state = _trigger_state()
    fingerprint = _mac("trigger", message_key)
    return fingerprint in state["keys"]


def _dispatch(signal, message_key):
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if "/" not in repo or not token:
        raise RuntimeError("github_dispatch_configuration_missing")
    url = f"{api}/repos/{quote(repo, safe='/')}/dispatches"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "event_type": "aldi-usage-alert",
            "client_payload": {
                "provider": "alditalk",
                "signal": signal,
                "message_key": message_key,
                "preclaimed": False,
            },
        },
        timeout=20,
    )
    if response.status_code != 204:
        raise RuntimeError(f"github_dispatch_http_{response.status_code}")


def _mailboxes():
    result = []
    for index in (1, 2):
        host = os.environ.get(f"MAILBOX_{index}_HOST", "").strip()
        user = os.environ.get(f"MAILBOX_{index}_USER", "").strip()
        password = os.environ.get(f"MAILBOX_{index}_PASS", "")
        port_text = os.environ.get(f"MAILBOX_{index}_PORT", "993").strip() or "993"
        if not (host or user or password):
            continue
        if not (host and user and password):
            raise RuntimeError(f"mailbox_{index}_configuration_incomplete")
        result.append((index, host, int(port_text), user, password))
    return result


def _poll_one(index, host, port, user, password):
    dispatched = 0
    context = ssl.create_default_context()
    with imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=20) as client:
        client.login(user, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError(f"mailbox_{index}_select_failed")
        cursor = MailboxCursor(host, user, client)
        for message_num in cursor.batch():
            status, fetched = client.uid("fetch", message_num, "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                raise RuntimeError("mailbox_uid_fetch_failed")
            raw = next((item[1] for item in fetched
                        if isinstance(item, tuple) and isinstance(item[1], (bytes, bytearray))), None)
            if raw is None:
                raise RuntimeError("mailbox_uid_message_missing")
            message = email.message_from_bytes(bytes(raw))
            signal = _signal(message)
            if signal != "consumed":
                continue
            message_key = _message_key(message, bytes(raw))
            if (_already_seen(_legacy_message_key(message, bytes(raw)))
                    or _already_seen(message_key)):
                continue
            _dispatch(signal, message_key)
            dispatched += 1
        cursor.commit()
    return dispatched


def main():
    mailboxes = _mailboxes()
    if not mailboxes:
        print(json.dumps({"configured_mailboxes": 0, "dispatched": 0}), flush=True)
        return 0
    dispatched = 0
    failures = []
    for config in mailboxes:
        try:
            dispatched += _poll_one(*config)
        except Exception as exc:
            failures.append({"mailbox": config[0], "error": type(exc).__name__})
    print(json.dumps({
        "configured_mailboxes": len(mailboxes),
        "dispatched": dispatched,
        "failed_mailboxes": failures,
    }), flush=True)
    return 2 if failures and dispatched == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
