"""Read authenticated Gmail changes; ALDI mail is a wake-up, never booking evidence.

Official API references: docs/v5-deployment-findings.md. No mailbox writes are
performed, except an explicit ``watch(topic)`` registration requested by setup.
The parser accepts Gmail API and the connected Gmail reader representations.
It relies on Gmail's server-added Authentication-Results, not quoted mail text.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import time
import unicodedata
from email.header import decode_header, make_header
from email.utils import getaddresses
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

from lite.models import MailEvent


ALDI_SENDER = "noreply@alditalk-kundenbetreuung.de"
ALDI_DOMAIN = "alditalk-kundenbetreuung.de"
ALDI_SUBJECT = "Verbrauch deines Datenvolumens"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
_MAX_BYTES = 2 * 1024 * 1024


class GmailError(RuntimeError):
    """Sanitized Gmail failure: never includes provider payload or credentials."""


class HistoryExpired(GmailError):
    """Explicit resynchronization needed; do not silently replay historic mail."""


class MailboxMismatch(GmailError):
    """OAuth principal does not match the explicitly configured mailbox."""


class MessageUnavailable(GmailError):
    """Message was removed before it could be read; do not invent its contents."""


def _mailbox(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("mailbox_required")
    value = value.strip().lower()
    if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
        raise ValueError("mailbox_invalid")
    return value


def _account(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
        raise ValueError("explicit_account_alias_required")
    return value


def _header_map(payload: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for item in payload.get("headers") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("value"), str):
            result.setdefault(item["name"].lower(), []).append(item["value"])
    return result


def _decoded_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError, ValueError):
        return ""


def _authentic_aldi(headers: dict[str, list[str]]) -> bool:
    # Use only the first top-level result inserted by Gmail. Never search body,
    # ARC-Authentication-Results, attachments, or a later forged pass header.
    results = headers.get("authentication-results") or []
    if not results:
        return False
    result = re.sub(r"\s+", " ", results[0]).strip().lower()
    clauses = result.split(";")
    if clauses[0].strip() != "mx.google.com":
        return False
    checks = {}
    for clause in clauses[1:]:
        match = re.match(r"\s*(dkim|spf|dmarc)\s*=\s*(\w+)\b", clause)
        if match:
            checks.setdefault(match.group(1), []).append((match.group(2), clause))
    if not all(key in checks for key in ("dkim", "spf", "dmarc")):
        return False
    domain = re.escape(ALDI_DOMAIN)
    dkim = any(status == "pass" and re.search(
        rf"\bheader\.(?:d|i)\s*=\s*(?:[^\s;@]*@)?{domain}(?=[\s;]|$)", clause
    ) for status, clause in checks["dkim"])
    spf = any(status == "pass" and re.search(
        rf"\bsmtp\.mailfrom\s*=\s*[^\s;@]+@(?:bounce\.)?{domain}(?=[\s;]|$)", clause
    ) for status, clause in checks["spf"])
    dmarc = any(status == "pass" and re.search(
        rf"\bheader\.from\s*=\s*{domain}(?=[\s;]|$)", clause
    ) for status, clause in checks["dmarc"])
    signature = any(re.search(
        rf"(?:^|;)\s*d\s*=\s*{domain}\s*(?:;|$)", value.lower()
    ) for value in headers.get("dkim-signature") or [])
    return dkim and spf and dmarc and signature


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head", "blockquote"}:
            self.hidden += 1
        if not self.hidden and tag in {"br", "p", "div", "td", "tr", "li"}:
            self.text.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head", "blockquote"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "td", "tr", "li"}:
            self.text.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def _body_text(payload: dict, depth: int = 0) -> list[str]:
    if depth > 20 or payload.get("filename"):
        return []
    mime = str(payload.get("mimeType") or payload.get("mime_type") or "").lower()
    # Forwarded attached messages cannot supply headers or trigger text.
    if mime == "message/rfc822":
        return []
    if mime.startswith("multipart/"):
        result = []
        for part in payload.get("parts") or []:
            if isinstance(part, dict):
                result.extend(_body_text(part, depth + 1))
        return result
    if mime not in {"text/plain", "text/html"}:
        return []
    body = payload.get("body") or {}
    if not isinstance(body, dict):
        return []
    text = body.get("content")
    if not isinstance(text, str):
        encoded = body.get("data") or body.get("base64_url_content")
        if not isinstance(encoded, str) or len(encoded) > _MAX_BYTES:
            return []
        try:
            decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            content_type = " ".join(_header_map(payload).get("content-type") or [])
            charset_match = re.search(r"charset\s*=\s*[\"']?([^\s;\"']+)", content_type, re.I)
            charset = charset_match.group(1) if charset_match else "utf-8"
            text = decoded.decode(charset, errors="strict")
        except (ValueError, LookupError, UnicodeError):
            return []
    if len(text) > _MAX_BYTES:
        return []
    if mime == "text/html":
        parser = _HTMLText()
        try:
            parser.feed(text)
        except (ValueError, RecursionError):
            return []
        text = "".join(parser.text)
    normalized = unicodedata.normalize("NFKC", text).replace("\u2010", "-").replace("\u2011", "-")
    return [" ".join(normalized.split())]


def parse_gmail_message(message_dict: dict, mailbox: str, account: str) -> MailEvent | None:
    """Require authenticated original ALDI mail and explicit account mapping.

    ``account`` is a configured, previously verified provider-account alias.
    It cannot be reconstructed from a greeting, mailbox name or mail link.
    For live use, ``message_dict`` must originate from authenticated Gmail reads.
    """
    mailbox = _mailbox(mailbox)
    account = _account(account)
    if not isinstance(message_dict, dict):
        return None
    payload = message_dict.get("payload")
    mail_id = message_dict.get("id")
    if not isinstance(payload, dict) or not isinstance(mail_id, str) or not re.fullmatch(r"[a-fA-F0-9]{1,80}", mail_id):
        return None
    labels = message_dict.get("labelIds") or message_dict.get("label_ids") or []
    if set(labels) & {"SENT", "DRAFT", "SPAM", "TRASH"}:
        return None
    headers = _header_map(payload)
    senders = headers.get("from") or []
    subjects = headers.get("subject") or []
    if len(senders) != 1 or len(subjects) != 1:
        return None
    addresses = getaddresses(senders)
    if len(addresses) != 1 or addresses[0][1].lower() != ALDI_SENDER:
        return None
    if _decoded_header(subjects[0]).strip() != ALDI_SUBJECT or not _authentic_aldi(headers):
        return None
    # Gmail's actual delivery address is stronger than a display-name/greeting.
    delivered = {address.lower() for _, address in getaddresses(headers.get("delivered-to") or [])}
    if mailbox not in delivered:
        return None
    raw_date = message_dict.get("internalDate", message_dict.get("internal_date"))
    try:
        if isinstance(raw_date, bool) or not re.fullmatch(r"\d{1,16}", str(raw_date)):
            return None
        received_at = int(raw_date) / 1000
        if not math.isfinite(received_at) or received_at <= 0 or received_at > time.time() + 300:
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    kinds = set()
    for text in _body_text(payload):
        if re.search(r"\bdu hast\s+80\s*%\s+des Datenvolumens in der aktuellen Optionslaufzeit genutzt\b", text, re.I):
            kinds.add("warning80")
        if re.search(r"\bdas Datenvolumen deines Tarifs oder einer Zusatz[-\s]*Option ist verbraucht\b", text, re.I):
            kinds.add("exhausted")
    if len(kinds) != 1:
        return None
    event_id = hashlib.sha256((mailbox + "\0" + mail_id).encode()).hexdigest()
    return MailEvent(event_id=event_id, mailbox=mailbox, mail_id=mail_id,
                     received_at=received_at, kind=kinds.pop(), account=account)


class GmailClient:
    """Small synchronous Gmail API reader with bounded network operations.

    OAuth credentials stay in memory/environment. Error strings contain only
    failure classes/status codes. urllib preserves normal TLS/proxy settings.
    """

    def __init__(self, mailbox: str, client_id: str | None = None,
                 client_secret: str | None = None, refresh_token: str | None = None,
                 *, timeout: float = 20, opener=None):
        self.mailbox = _mailbox(mailbox)
        self._client_id = client_id or os.environ.get("GMAIL_CLIENT_ID", "")
        self._client_secret = client_secret or os.environ.get("GMAIL_CLIENT_SECRET", "")
        self._refresh_token = refresh_token or os.environ.get("GMAIL_REFRESH_TOKEN", "")
        if not all((self._client_id, self._client_secret, self._refresh_token)):
            raise GmailError("gmail_oauth_credentials_missing")
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 60:
            raise ValueError("gmail_timeout_invalid")
        self._timeout = timeout
        self._opener = opener or build_opener()
        self._access_token = ""
        self._token_expires_at = 0.0
        self._verified = False

    def _json(self, request: Request) -> dict:
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                data = response.read(_MAX_BYTES + 1)
                if len(data) > _MAX_BYTES:
                    raise GmailError("gmail_response_too_large")
            result = json.loads(data)
            if not isinstance(result, dict):
                raise GmailError("gmail_response_invalid")
            return result
        except HTTPError:
            raise
        except (URLError, TimeoutError, OSError):
            raise GmailError("gmail_network_error") from None
        except (ValueError, UnicodeError):
            raise GmailError("gmail_response_invalid") from None

    def _token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        data = urlencode({"client_id": self._client_id, "client_secret": self._client_secret,
                          "refresh_token": self._refresh_token, "grant_type": "refresh_token"}).encode()
        try:
            response = self._json(Request(TOKEN_URL, data=data,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"}))
        except HTTPError as error:
            raise GmailError(f"gmail_oauth_http_{error.code}") from None
        token = response.get("access_token")
        try:
            expires = float(response.get("expires_in", 0))
        except (TypeError, ValueError):
            expires = 0
        if not isinstance(token, str) or not token or not math.isfinite(expires) or expires <= 0:
            raise GmailError("gmail_oauth_response_invalid")
        self._access_token = token
        self._token_expires_at = time.monotonic() + max(0, expires - 60)
        return token

    def _request(self, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        url = GMAIL_API + path
        if params:
            url += "?" + urlencode(params, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(2):
            request = Request(url, data=data, headers={"Authorization": "Bearer " + self._token(),
                              "Content-Type": "application/json"})
            try:
                return self._json(request)
            except HTTPError as error:
                if error.code == 401 and attempt == 0:
                    self._access_token = ""
                    self._verified = False
                    continue
                if error.code == 404 and path == "/history":
                    raise HistoryExpired("gmail_history_expired") from None
                if error.code == 404 and path.startswith("/messages/"):
                    raise MessageUnavailable("gmail_message_unavailable") from None
                raise GmailError(f"gmail_http_{error.code}") from None
        raise GmailError("gmail_auth_failed")

    def get_profile(self) -> dict:
        profile = self._request("/profile")
        if str(profile.get("emailAddress", "")).strip().lower() != self.mailbox:
            raise MailboxMismatch("gmail_mailbox_mismatch")
        if not re.fullmatch(r"\d+", str(profile.get("historyId", ""))):
            raise GmailError("gmail_profile_invalid")
        self._verified = True
        return profile

    def _verify(self):
        if not self._verified:
            self.get_profile()

    def read_message(self, message_id: str) -> dict:
        if not isinstance(message_id, str) or not re.fullmatch(r"[a-fA-F0-9]{1,80}", message_id):
            raise ValueError("gmail_message_id_invalid")
        self._verify()
        message = self._request("/messages/" + quote(message_id, safe=""), {"format": "full"})
        if message.get("id") != message_id:
            raise GmailError("gmail_message_id_mismatch")
        return message

    def events_since(self, history_id: str, account: str) -> tuple[list[MailEvent], str]:
        account = _account(account)
        if not re.fullmatch(r"\d+", str(history_id)):
            raise ValueError("gmail_history_id_invalid")
        self._verify()
        events: list[MailEvent] = []
        seen: set[str] = set()
        tokens: set[str] = set()
        page_token = None
        cursor = int(history_id)
        while True:
            params = {"startHistoryId": str(history_id), "historyTypes": "messageAdded", "maxResults": 100}
            if page_token:
                params["pageToken"] = page_token
            page = self._request("/history", params)
            response_id = str(page.get("historyId", ""))
            if not re.fullmatch(r"\d+", response_id) or int(response_id) < cursor:
                raise GmailError("gmail_history_response_invalid")
            cursor = int(response_id)
            for history in page.get("history") or []:
                if not isinstance(history, dict):
                    raise GmailError("gmail_history_response_invalid")
                for added in history.get("messagesAdded") or []:
                    mail_id = (added.get("message") or {}).get("id") if isinstance(added, dict) else None
                    if not isinstance(mail_id, str):
                        raise GmailError("gmail_history_response_invalid")
                    if mail_id in seen:
                        continue
                    seen.add(mail_id)
                    try:
                        message = self.read_message(mail_id)
                    except MessageUnavailable:
                        continue
                    event = parse_gmail_message(message, self.mailbox, account)
                    if event is not None:
                        events.append(event)
            page_token = page.get("nextPageToken")
            if not page_token:
                break
            if not isinstance(page_token, str) or page_token in tokens:
                raise GmailError("gmail_history_pagination_invalid")
            tokens.add(page_token)
            if len(tokens) > 1000:
                raise GmailError("gmail_history_page_limit")
        events.sort(key=lambda event: (event.received_at, event.mail_id))
        return events, str(cursor)

    def watch(self, topic: str) -> dict:
        """Explicit setup/renewal only; does not create a topic/subscription."""
        if not isinstance(topic, str) or not re.fullmatch(r"projects/[a-z][a-z0-9-]{4,61}[a-z0-9]/topics/[A-Za-z][A-Za-z0-9_.~+%-]{2,254}", topic):
            raise ValueError("gmail_topic_invalid")
        self._verify()
        response = self._request("/watch", body={"topicName": topic})
        if not re.fullmatch(r"\d+", str(response.get("historyId", ""))) or not re.fullmatch(r"\d+", str(response.get("expiration", ""))):
            raise GmailError("gmail_watch_response_invalid")
        return response

    def scan_recent(self, account: str, max_results: int = 10,
                    max_age_seconds: float = 86400) -> list[MailEvent]:
        """Bounded read-only discovery for DRY_RUN; never silent crash replay."""
        account = _account(account)
        if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 100:
            raise ValueError("gmail_scan_limit_invalid")
        if not math.isfinite(max_age_seconds) or not 0 < max_age_seconds <= 7 * 86400:
            raise ValueError("gmail_scan_age_invalid")
        self._verify()
        oldest = time.time() - max_age_seconds
        query = f'from:{ALDI_SENDER} subject:"{ALDI_SUBJECT}" after:{int(oldest)} -in:spam -in:trash'
        page = self._request("/messages", {"q": query, "maxResults": max_results})
        events, seen = [], set()
        for item in (page.get("messages") or [])[:max_results]:
            mail_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(mail_id, str):
                raise GmailError("gmail_scan_response_invalid")
            if mail_id in seen:
                continue
            seen.add(mail_id)
            try:
                message = self.read_message(mail_id)
            except MessageUnavailable:
                continue
            event = parse_gmail_message(message, self.mailbox, account)
            if event is not None and event.received_at >= oldest:
                events.append(event)
        events.sort(key=lambda event: (event.received_at, event.mail_id))
        return events
