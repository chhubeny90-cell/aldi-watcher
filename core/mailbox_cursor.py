"""Durable read-only mailbox scan position, separate from message deduplication.

Only an HMAC mailbox identifier, UIDVALIDITY and the last processed UID are
persisted. A changed UIDVALIDITY rescans provider mail without discarding
immutable Message-ID deduplication maintained by the caller.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

from github_hardening_state import _aux_path, _mac, _read_json, _write_json


VERSION = 1
MAX_MAILBOXES = 128
MAX_UID = 2 ** 32 - 1
INITIAL_DAYS = 30
MAX_BATCH = 50
MAX_SEARCH_BYTES = 2 * 1024 * 1024


class MailboxCursorError(RuntimeError):
    """Fixed reason codes only; never upstream responses or mailbox identities."""


def _uid(value, *, allow_zero=False):
    if not isinstance(value, bytes) or not re.fullmatch(rb"[0-9]{1,10}", value):
        raise MailboxCursorError("mailbox_uid_invalid")
    number = int(value)
    if not (0 if allow_zero else 1) <= number <= MAX_UID or str(number).encode() != value:
        raise MailboxCursorError("mailbox_uid_invalid")
    return number


def _response_uid(client, name):
    try:
        status, values = client.response(name)
    except Exception:
        raise MailboxCursorError("mailbox_uid_metadata_unavailable") from None
    if status not in {name, "OK"} or not isinstance(values, list) or len(values) != 1:
        raise MailboxCursorError("mailbox_uid_metadata_invalid")
    return _uid(values[0])


def _records(payload):
    if (not isinstance(payload, dict) or set(payload) != {"version", "mailboxes"}
            or type(payload["version"]) is not int or payload["version"] != VERSION
            or not isinstance(payload["mailboxes"], dict)
            or len(payload["mailboxes"]) > MAX_MAILBOXES):
        raise MailboxCursorError("mailbox_cursor_invalid")
    records = {}
    for key, record in payload["mailboxes"].items():
        if (not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                or not isinstance(record, dict) or set(record) != {"uidvalidity", "last_uid"}
                or not isinstance(record["uidvalidity"], str)
                or type(record["last_uid"]) is not int or not 0 <= record["last_uid"] <= MAX_UID):
            raise MailboxCursorError("mailbox_cursor_invalid")
        try:
            _uid(record["uidvalidity"].encode("ascii"))
        except (MailboxCursorError, UnicodeError):
            raise MailboxCursorError("mailbox_cursor_invalid") from None
        records[key] = dict(record)
    return records


class MailboxCursor:
    def __init__(self, host, user, client):
        if (not isinstance(host, str) or not isinstance(user, str)
                or not host.strip() or not user.strip() or len(host) > 512 or len(user) > 512):
            raise MailboxCursorError("mailbox_identity_invalid")
        identity = json.dumps([host.strip().casefold(), user.strip(), "INBOX"],
                              ensure_ascii=True, separators=(",", ":"))
        if not os.environ.get("ALDI_RECOVERY_KEY", "").strip():
            raise MailboxCursorError("mailbox_cursor_key_unavailable")
        try:
            self._identity = _mac("mailbox-cursor-v1", identity)
        except Exception:
            raise MailboxCursorError("mailbox_cursor_key_unavailable") from None
        self._client = client
        self.uidvalidity = str(_response_uid(client, "UIDVALIDITY"))
        self._path = _aux_path("mailbox-cursors")
        try:
            current = _read_json(self._path)
        except Exception:
            raise MailboxCursorError("mailbox_cursor_read_failed") from None
        self._sha, payload = current if current is not None else (None, {"version": VERSION, "mailboxes": {}})
        self._records = _records(payload)
        previous = self._records.get(self._identity)
        if previous is None and len(self._records) >= MAX_MAILBOXES:
            raise MailboxCursorError("mailbox_cursor_capacity_reached")
        self.validity_changed = previous is not None and previous["uidvalidity"] != self.uidvalidity
        self.initial = previous is None or self.validity_changed
        self.last_uid = 0 if self.initial else previous["last_uid"]
        self.backlog = 0
        self._selected = None
        self._commit_position = None
        self._poisoned = False
        self._committed = False

    def batch(self, now=None, limit=MAX_BATCH):
        """Select earliest pending messages; truncation never skips the backlog."""
        if self._poisoned or self._committed or self._selected is not None:
            raise MailboxCursorError("mailbox_cursor_not_reusable")
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise MailboxCursorError("mailbox_batch_limit_invalid")
        if self.validity_changed:
            # UID renumbering must not hide pending mail older than the virgin
            # scan window. Immutable message deduplication handles replay.
            criteria = ("FROM", "alditalk-kundenbetreuung.de")
        elif self.initial:
            reference = now or datetime.now(timezone.utc)
            if reference.tzinfo is None:
                raise MailboxCursorError("mailbox_naive_scan_reference")
            since = reference.astimezone(timezone.utc) - timedelta(days=INITIAL_DAYS)
            months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
            date = f"{since.day:02d}-{months[since.month - 1]}-{since.year:04d}"
            criteria = ("SINCE", date, "FROM", "alditalk-kundenbetreuung.de")
        else:
            criteria = ("UID", f"{self.last_uid + 1}:*", "FROM", "alditalk-kundenbetreuung.de")
        try:
            status, data = self._client.uid("search", None, *criteria)
        except Exception:
            raise MailboxCursorError("mailbox_uid_search_failed") from None
        if (status != "OK" or not isinstance(data, list) or len(data) != 1
                or not isinstance(data[0], bytes) or len(data[0]) > MAX_SEARCH_BYTES):
            raise MailboxCursorError("mailbox_uid_search_failed")
        numbers = sorted({_uid(item) for item in data[0].split()})
        # IMAP's 'N:*' can include the final existing UID even when it is < N.
        if not self.initial:
            numbers = [uid for uid in numbers if uid > self.last_uid]
        selected = numbers[:limit]
        self.backlog = len(numbers) - len(selected)
        self._commit_position = selected[-1] if selected else self.last_uid
        if self.initial and not selected:
            # No recent provider mail: start after the select-time mailbox tail,
            # rather than scanning all older mail on the next invocation.
            self._commit_position = _response_uid(self._client, "UIDNEXT") - 1
        self._selected = [str(uid).encode("ascii") for uid in selected]
        return list(self._selected)

    def commit(self, last_uid=None):
        """Call only after every selected message and dedup write succeeded."""
        if self._poisoned or self._committed or self._selected is None:
            raise MailboxCursorError("mailbox_cursor_not_reusable")
        if last_uid is not None and (type(last_uid) is not int or last_uid != self._commit_position):
            raise MailboxCursorError("mailbox_cursor_position_mismatch")
        record = {"uidvalidity": self.uidvalidity, "last_uid": self._commit_position}
        if self._records.get(self._identity) == record:
            self._committed = True
            return
        payload = {"version": VERSION, "mailboxes": {**self._records, self._identity: record}}
        try:
            _write_json(self._path, payload, self._sha, message="Persist mailbox UID cursor [skip ci]")
            confirmed = _read_json(self._path)
            if confirmed is None or confirmed[1] != payload:
                raise MailboxCursorError("mailbox_cursor_write_unconfirmed")
            confirmed_records = _records(confirmed[1])
        except Exception:
            self._poisoned = True
            raise MailboxCursorError("mailbox_cursor_write_unconfirmed") from None
        self.last_uid = self._commit_position
        self._sha, self._records = confirmed[0], confirmed_records
        self._committed = True
