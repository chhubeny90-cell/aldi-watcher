"""Synthetic mailbox UID progress with a fake CAS store and no network."""
import copy
from datetime import datetime, timezone
import json

import pytest

import core.mailbox_cursor as cursor_module
from core.mailbox_cursor import MailboxCursor, MailboxCursorError


NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)
HOST = "imap.example.invalid"
USER = "synthetic-user@example.invalid"


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("ALDI_RECOVERY_KEY", "synthetic-dedup-key")
    data = {"current": None, "writes": []}

    def read(path):
        assert path.endswith(".mailbox-cursors.json")
        return copy.deepcopy(data["current"])

    def write(path, payload, sha, message=None):
        assert "[skip ci]" in message
        current = data["current"]
        expected = current[0] if current is not None else None
        if sha != expected:
            raise RuntimeError("github_aux_state_conflict")
        data["writes"].append(copy.deepcopy(payload))
        data["current"] = ("revision-" + str(len(data["writes"])), copy.deepcopy(payload))

    monkeypatch.setattr(cursor_module, "_read_json", read)
    monkeypatch.setattr(cursor_module, "_write_json", write)
    data["write"] = write
    return data


class Inbox:
    def __init__(self, uids=(), validity=123, recent=None, quirk=False):
        self.uids = list(uids)
        self.validity = validity
        self.recent = self.uids if recent is None else list(recent)
        self.quirk = quirk
        self.calls = []

    def response(self, name):
        self.calls.append(("response", name))
        assert name in {"UIDVALIDITY", "UIDNEXT"}
        value = self.validity if name == "UIDVALIDITY" else max(self.uids, default=0) + 1
        return name, [str(value).encode()]

    def uid(self, command, *args):
        assert command == "search"
        self.calls.append((command, *args))
        assert args[0] is None and args[-2:] == ("FROM", "alditalk-kundenbetreuung.de")
        assert "UNSEEN" not in args
        if args[1] == "SINCE":
            values = self.recent
        elif args[1] == "FROM":
            values = self.uids
        else:
            assert args[1] == "UID"
            lower = int(args[2].split(":", 1)[0])
            values = [uid for uid in self.uids if uid >= lower]
            if not values and self.quirk and self.uids:
                values = [max(self.uids)]
        return "OK", [b" ".join(str(uid).encode() for uid in values)]


def test_initial_scan_uses_recent_window_and_readonly_uid_search(store):
    inbox = Inbox(range(1, 101), recent=range(51, 101))
    cursor = MailboxCursor(HOST, USER, inbox)
    assert cursor.initial is True and cursor.validity_changed is False
    assert cursor.batch(NOW) == [str(uid).encode() for uid in range(51, 101)]
    assert cursor.backlog == 0
    assert inbox.calls[1] == ("search", None, "SINCE", "26-Sep-2026", "FROM", "alditalk-kundenbetreuung.de")
    assert store["writes"] == []
    cursor.commit()
    assert cursor.last_uid == 100


def test_backlog_over_fifty_resumes_earliest_pending_without_silent_gap(store):
    batches = []
    for expected_backlog in (70, 20, 0):
        inbox = Inbox(range(1, 121))
        cursor = MailboxCursor(HOST, USER, inbox)
        batch = cursor.batch(NOW)
        batches.extend(map(int, batch))
        assert cursor.backlog == expected_backlog
        if not cursor.initial:
            assert inbox.calls[1][2] == "UID"
            assert "SINCE" not in inbox.calls[1]
        cursor.commit()
    assert batches == list(range(1, 121))
    assert cursor.last_uid == 120
    assert len(store["writes"]) == 3


def test_restart_cursor_does_not_depend_on_read_unread_flags(store):
    first = MailboxCursor(HOST, USER, Inbox([7, 12]))
    assert first.batch(NOW) == [b"7", b"12"]
    first.commit()
    second_inbox = Inbox([7, 12, 16])
    second = MailboxCursor(HOST, USER, second_inbox)
    assert second.batch(NOW) == [b"16"]
    assert second_inbox.calls[1] == ("search", None, "UID", "13:*", "FROM", "alditalk-kundenbetreuung.de")


def test_imap_uid_range_star_quirk_never_replays_last_existing_uid(store):
    first = MailboxCursor(HOST, USER, Inbox([42]))
    first.batch(NOW)
    first.commit()
    cursor = MailboxCursor(HOST, USER, Inbox([42], quirk=True))
    assert cursor.batch(NOW) == []
    cursor.commit()
    assert len(store["writes"]) == 1


def test_empty_initial_scan_anchors_after_existing_older_mail(store):
    first = MailboxCursor(HOST, USER, Inbox(range(1, 301), recent=[]))
    assert first.batch(NOW) == []
    first.commit()
    assert first.last_uid == 300
    second = MailboxCursor(HOST, USER, Inbox(range(1, 302)))
    assert second.batch(NOW) == [b"301"]


def test_empty_mailbox_records_validity_without_inventing_message_uid(store):
    cursor = MailboxCursor(HOST, USER, Inbox())
    assert cursor.batch(NOW) == []
    cursor.commit()
    assert cursor.last_uid == 0


def test_uidvalidity_change_rescans_all_provider_mail_without_touching_message_history(store):
    first = MailboxCursor(HOST, USER, Inbox([100, 150], validity=1))
    first.batch(NOW)
    first.commit()
    changed_inbox = Inbox([1, 2, 3], validity=2, recent=[])
    changed = MailboxCursor(HOST, USER, changed_inbox)
    assert changed.initial is True and changed.validity_changed is True
    assert changed.last_uid == 0
    assert changed.batch(NOW) == [b"1", b"2", b"3"]
    assert changed_inbox.calls[1] == ("search", None, "FROM", "alditalk-kundenbetreuung.de")
    assert "SINCE" not in changed_inbox.calls[1]
    changed.commit()
    assert len(store["current"][1]["mailboxes"]) == 1
    record = next(iter(store["current"][1]["mailboxes"].values()))
    assert record == {"uidvalidity": "2", "last_uid": 3}


def test_fetch_or_dedup_failure_before_commit_preserves_cursor_for_restart(store):
    first = MailboxCursor(HOST, USER, Inbox([3, 4, 5]))
    assert first.batch(NOW) == [b"3", b"4", b"5"]
    # The caller failed while fetching or recording a message; no commit is made.
    assert store["current"] is None
    restarted = MailboxCursor(HOST, USER, Inbox([3, 4, 5]))
    assert restarted.batch(NOW) == [b"3", b"4", b"5"]


def test_mailbox_cursors_preserve_other_mailboxes_and_hide_addresses(store):
    first = MailboxCursor(HOST, USER, Inbox([1]))
    first.batch(NOW)
    first.commit()
    second = MailboxCursor("IMAP.EXAMPLE.INVALID", "another-user@example.invalid", Inbox([2]))
    second.batch(NOW)
    second.commit()
    assert len(store["current"][1]["mailboxes"]) == 2
    public = json.dumps(store["writes"])
    assert "imap.example.invalid" not in public.lower()
    assert "synthetic-user" not in public and "another-user" not in public
    assert "INBOX" not in public and "synthetic-dedup-key" not in public
    assert all(len(key) == 64 for key in store["current"][1]["mailboxes"])


def test_equivalent_host_case_uses_same_cursor(store):
    first = MailboxCursor(HOST, USER, Inbox([9]))
    first.batch(NOW)
    first.commit()
    same = MailboxCursor(HOST.upper(), USER, Inbox([9, 10]))
    assert same.initial is False and same.batch(NOW) == [b"10"]


def test_stale_cas_cursor_cannot_overwrite_newer_position(store):
    first = MailboxCursor(HOST, USER, Inbox([1, 2]))
    stale = MailboxCursor(HOST, USER, Inbox([1]))
    first.batch(NOW)
    stale.batch(NOW)
    first.commit()
    with pytest.raises(MailboxCursorError, match="^mailbox_cursor_write_unconfirmed$"):
        stale.commit()
    assert len(store["writes"]) == 1
    with pytest.raises(MailboxCursorError, match="mailbox_cursor_not_reusable"):
        stale.commit()


@pytest.mark.parametrize("committed", [False, True])
def test_write_timeout_poison_prevents_blind_retry(store, monkeypatch, committed):
    def uncertain(*args, **kwargs):
        if committed:
            store["write"](*args, **kwargs)
        raise TimeoutError("PRIVATE_SERVER_RESPONSE")
    monkeypatch.setattr(cursor_module, "_write_json", uncertain)
    cursor = MailboxCursor(HOST, USER, Inbox([1]))
    cursor.batch(NOW)
    with pytest.raises(MailboxCursorError, match="^mailbox_cursor_write_unconfirmed$") as error:
        cursor.commit()
    assert "PRIVATE" not in str(error.value)
    with pytest.raises(MailboxCursorError, match="mailbox_cursor_not_reusable"):
        cursor.commit()
    assert len(store["writes"]) == int(committed)


def test_changed_readback_is_not_a_confirmed_write(store, monkeypatch):
    cursor = MailboxCursor(HOST, USER, Inbox([1]))
    cursor.batch(NOW)
    monkeypatch.setattr(cursor_module, "_read_json", lambda path: None)
    with pytest.raises(MailboxCursorError, match="mailbox_cursor_write_unconfirmed"):
        cursor.commit()
    with pytest.raises(MailboxCursorError, match="mailbox_cursor_not_reusable"):
        cursor.commit()


@pytest.mark.parametrize("payload", [
    {}, {"version": True, "mailboxes": {}}, {"version": 2, "mailboxes": {}},
    {"version": 1, "mailboxes": []},
    {"version": 1, "mailboxes": {"private-user@example.invalid": {"uidvalidity": "1", "last_uid": 0}}},
    {"version": 1, "mailboxes": {"a" * 64: {"uidvalidity": 1, "last_uid": 0}}},
    {"version": 1, "mailboxes": {"a" * 64: {"uidvalidity": "1", "last_uid": True}}},
    {"version": 1, "mailboxes": {"a" * 64: {"uidvalidity": "0", "last_uid": 0}}},
    {"version": 1, "mailboxes": {"a" * 64: {"uidvalidity": "1", "last_uid": -1}}},
])
def test_corrupt_remote_cursor_never_becomes_empty_history(store, payload):
    store["current"] = ("revision-1", payload)
    with pytest.raises(MailboxCursorError, match="^mailbox_cursor_invalid$"):
        MailboxCursor(HOST, USER, Inbox([1]))
    assert store["writes"] == []


def test_missing_mail_key_cannot_fall_back_to_provider_password(store, monkeypatch):
    monkeypatch.delenv("ALDI_RECOVERY_KEY")
    monkeypatch.setenv("ALDI_PASS", "private-provider-password")
    with pytest.raises(MailboxCursorError, match="^mailbox_cursor_key_unavailable$"):
        MailboxCursor(HOST, USER, Inbox([1]))
    assert store["writes"] == []


def test_unavailable_remote_state_is_not_empty_cursor(store, monkeypatch):
    def fail(path):
        raise RuntimeError("PRIVATE_STATE_DETAIL")
    monkeypatch.setattr(cursor_module, "_read_json", fail)
    with pytest.raises(MailboxCursorError, match="^mailbox_cursor_read_failed$"):
        MailboxCursor(HOST, USER, Inbox([1]))


@pytest.mark.parametrize("data", [[b"PRIVATE_UID"], [b"0"], [b"01"], [b"4294967296"], [None], []])
def test_invalid_uidvalidity_blocks_scan(store, data):
    class BadInbox(Inbox):
        def response(self, name):
            return name, data
    with pytest.raises(MailboxCursorError):
        MailboxCursor(HOST, USER, BadInbox([1]))
    assert store["writes"] == []


def test_failed_search_does_not_advance_cursor(store):
    class BadInbox(Inbox):
        def uid(self, *args):
            return "NO", [b"PRIVATE_SEARCH_RESPONSE"]
    cursor = MailboxCursor(HOST, USER, BadInbox([1]))
    with pytest.raises(MailboxCursorError, match="^mailbox_uid_search_failed$"):
        cursor.batch(NOW)
    assert store["writes"] == []


def test_commit_cannot_skip_beyond_processed_batch(store):
    cursor = MailboxCursor(HOST, USER, Inbox([1, 2]))
    cursor.batch(NOW)
    with pytest.raises(MailboxCursorError, match="^mailbox_cursor_position_mismatch$"):
        cursor.commit(999)
    assert store["writes"] == []
    cursor.commit(2)


def test_commit_requires_a_successful_scan(store):
    cursor = MailboxCursor(HOST, USER, Inbox([1]))
    with pytest.raises(MailboxCursorError, match="mailbox_cursor_not_reusable"):
        cursor.commit()
    assert store["writes"] == []


@pytest.mark.parametrize("limit", [0, -1, True, 51])
def test_batch_limit_is_bounded(store, limit):
    cursor = MailboxCursor(HOST, USER, Inbox([1]))
    with pytest.raises(MailboxCursorError, match="mailbox_batch_limit_invalid"):
        cursor.batch(NOW, limit=limit)


def test_naive_initial_clock_is_rejected(store):
    cursor = MailboxCursor(HOST, USER, Inbox([1]))
    with pytest.raises(MailboxCursorError, match="mailbox_naive_scan_reference"):
        cursor.batch(datetime(2026, 10, 26))
