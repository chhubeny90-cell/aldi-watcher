"""Offline persistence tests; private state never appears in remote plaintext."""
import base64
import copy
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from cryptography.fernet import Fernet
import pytest
import requests

import github_encrypted_runtime as runtime
from core.database import Database


ACCOUNT = "01520000000"
COOKIE = {"name": "session", "value": "PRIVATE_SESSION", "domain": ".alditalk-kundenportal.de",
          "path": "/", "secure": True, "expires": None, "rest": {"HttpOnly": None},
          "domain_specified": True, "domain_initial_dot": True}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    key = Fernet.generate_key()
    monkeypatch.setenv("ALDI_STATE_ENCRYPTION_KEY", key.decode())
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.setattr(requests.sessions.Session, "request",
                        Mock(side_effect=AssertionError("unexpected network")))
    remote = {}
    writes = []
    serial = 0

    def read(path):
        return copy.deepcopy(remote.get(path))

    def write(path, payload, current_sha=None, **kwargs):
        nonlocal serial
        present = remote.get(path)
        assert current_sha == (present[0] if present else None), "CAS conflict"
        serial += 1
        remote[path] = (str(serial).zfill(40), copy.deepcopy(payload))
        writes.append((path, copy.deepcopy(payload), current_sha))

    read_mock = Mock(side_effect=read)
    write_mock = Mock(side_effect=write)
    monkeypatch.setattr(runtime, "_read_json", read_mock)
    monkeypatch.setattr(runtime, "_write_json", write_mock)
    journal = {"version": 2, "unresolved": [], "auth_retry_after": None}
    events = {}
    snapshot = Mock(side_effect=lambda: ("a" * 40, events, ("b" * 40, journal)))
    monkeypatch.setattr(runtime, "consistent_mail_snapshot", snapshot)
    return SimpleNamespace(key=key, remote=remote, writes=writes, read=read,
                           write=write, read_mock=read_mock, write_mock=write_mock,
                           journal=journal, events=events, snapshot=snapshot,
                           path=tmp_path / "journal.sqlite")


def initialize(storage):
    return runtime.RuntimeState().initialize(ACCOUNT, storage.path)


def test_initialization_marker_precedes_encrypted_snapshot(storage):
    state = initialize(storage)
    assert [entry[0] for entry in storage.writes] == [runtime.MARKER_PATH, runtime.STATE_PATH]
    assert storage.writes[0][2] is None
    assert storage.writes[1][2] is None
    assert state.cookies == []
    assert state.refill_accepted is False
    assert state.first_refill_authorized is False
    assert storage.path.stat().st_mode & 0o777 == 0o600
    envelope = storage.remote[runtime.STATE_PATH][1]
    assert set(envelope) == {"version", "ciphertext"}
    for sensitive in (ACCOUNT, "SQLite", "journal", "cookies"):
        assert sensitive not in json.dumps(envelope)


def test_full_journal_history_receipt_uniqueness_and_cookies_survive_new_instance(storage):
    state = initialize(storage)
    db = Database(str(storage.path))
    recharge_id = db.begin_recharge("alditalk", ACCOUNT)
    db.set_recharge_status(recharge_id, "SUCCESS")
    with sqlite3.connect(storage.path) as conn:
        conn.execute("CREATE TABLE recharge_provider_evidence (recharge_id TEXT PRIMARY KEY, "
                     "provider_operation_id TEXT NOT NULL UNIQUE, provider_resource_id TEXT NOT NULL)")
        conn.execute("INSERT INTO recharge_provider_evidence VALUES (?, ?, ?)",
                     (recharge_id, "PRIVATE_OPERATION", "PRIVATE_RESOURCE"))
    state.save_journal(storage.path)
    state.save_cookies([COOKIE])
    state.accept_refill()
    loaded = runtime.RuntimeState().load("+491520000000")
    restored_path = storage.path.with_name("restored.sqlite")
    loaded.restore_journal(restored_path)
    assert loaded.cookies == [COOKIE]
    assert loaded.refill_accepted is True
    with sqlite3.connect(restored_path) as conn:
        assert conn.execute("SELECT status FROM recharges WHERE recharge_id=?", (recharge_id,)).fetchone() == ("SUCCESS",)
        assert conn.execute("SELECT provider_operation_id FROM recharge_provider_evidence").fetchone() == ("PRIVATE_OPERATION",)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO recharge_provider_evidence VALUES ('other', 'PRIVATE_OPERATION', 'other')")
    remote_text = json.dumps(storage.remote)
    for secret in (ACCOUNT, "PRIVATE_SESSION", "PRIVATE_OPERATION", "PRIVATE_RESOURCE"):
        assert secret not in remote_text
    cookies = loaded.cookies
    cookies[0]["value"] = "changed"
    assert loaded.cookies[0]["value"] == "PRIVATE_SESSION"


def test_snapshot_includes_committed_wal(storage):
    state = initialize(storage)
    conn = sqlite3.connect(storage.path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE wal_test (value TEXT)")
        conn.execute("INSERT INTO wal_test VALUES ('private committed WAL')")
        conn.commit()
        assert Path(str(storage.path) + "-wal").is_file()
        state.save_journal(storage.path)
        target = storage.path.with_name("wal-restored.sqlite")
        runtime.RuntimeState().load(ACCOUNT).restore_journal(target)
        with sqlite3.connect(target) as restored:
            assert restored.execute("SELECT value FROM wal_test").fetchone() == ("private committed WAL",)
    finally:
        conn.close()


@pytest.mark.parametrize("key", [None, "bad-private-key"])
def test_missing_or_invalid_key_never_contacts_remote(storage, monkeypatch, key):
    if key is None:
        monkeypatch.delenv("ALDI_STATE_ENCRYPTION_KEY")
    else:
        monkeypatch.setenv("ALDI_STATE_ENCRYPTION_KEY", key)
    with pytest.raises(runtime.RuntimeStateError, match="^runtime_encryption_key_required$"):
        runtime.RuntimeState()
    storage.read_mock.assert_not_called()


@pytest.mark.parametrize("change", ["wrong_key", "wrong_account", "tampered", "bad_database"])
def test_unreadable_or_mismatched_state_fails_closed(storage, change):
    initialize(storage)
    account, key = ACCOUNT, storage.key
    sha, envelope = storage.remote[runtime.STATE_PATH]
    if change == "wrong_key":
        key = Fernet.generate_key()
    elif change == "wrong_account":
        account = "01529999999"
    elif change == "tampered":
        envelope["ciphertext"] = "PRIVATE_CORRUPTION"
    else:
        payload = json.loads(Fernet(key).decrypt(envelope["ciphertext"].encode()))
        payload["journal"] = base64.b64encode(b"SQLite format 3\x00INVALID").decode()
        envelope["ciphertext"] = Fernet(key).encrypt(json.dumps(payload).encode()).decode()
    storage.remote[runtime.STATE_PATH] = (sha, envelope)
    state = runtime.RuntimeState(key)
    with pytest.raises(runtime.RuntimeStateError, match="^runtime_state_invalid$"):
        state.load(account)
    writes_before = len(storage.writes)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_unconfirmed"):
        state.accept_refill()
    assert len(storage.writes) == writes_before


def test_missing_initialized_snapshot_cannot_be_recreated(storage):
    initialize(storage)
    del storage.remote[runtime.STATE_PATH]
    with pytest.raises(runtime.RuntimeStateError, match="runtime_initialized_state_missing"):
        runtime.RuntimeState().load(ACCOUNT)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_already_initialized"):
        runtime.RuntimeState().initialize(ACCOUNT, storage.path.with_name("replacement.sqlite"))
    assert not storage.path.with_name("replacement.sqlite").exists()


def test_existing_snapshot_without_marker_is_not_blessed_or_overwritten(storage):
    initialize(storage)
    del storage.remote[runtime.MARKER_PATH]
    with pytest.raises(runtime.RuntimeStateError, match="runtime_initialization_required"):
        runtime.RuntimeState().load(ACCOUNT)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_already_initialized"):
        runtime.RuntimeState().initialize(ACCOUNT, storage.path.with_name("replacement.sqlite"))


@pytest.mark.parametrize("condition", ["missing_journal", "unresolved", "in_flight", "quarantined"])
def test_bootstrap_never_hides_legacy_unresolved_state(storage, condition):
    if condition == "missing_journal":
        storage.snapshot.side_effect = None
        storage.snapshot.return_value = ("a" * 40, {}, None)
    elif condition == "unresolved":
        storage.journal["unresolved"] = [{"status": "UNKNOWN"}]
    else:
        storage.events["event"] = {"phase": "IN_FLIGHT" if condition == "in_flight" else "QUARANTINED_UNKNOWN"}
    with pytest.raises(runtime.RuntimeStateError, match="runtime_legacy_state_blocked"):
        initialize(storage)
    assert not storage.path.exists()
    assert storage.writes == []


@pytest.mark.parametrize("failure", ["conflict", "write_timeout", "readback_timeout", "readback_changed"])
def test_uncertain_persistence_poison_prevents_later_finally_overwrites(storage, failure):
    state = initialize(storage)
    writes_before = len(storage.writes)
    if failure == "conflict":
        storage.remote[runtime.STATE_PATH] = ("f" * 40, storage.remote[runtime.STATE_PATH][1])
    elif failure == "write_timeout":
        def uncertain_write(*args, **kwargs):
            storage.write(*args, **kwargs)
            raise TimeoutError("PRIVATE_TIMEOUT")
        storage.write_mock.side_effect = uncertain_write
    elif failure == "readback_timeout":
        storage.read_mock.side_effect = TimeoutError("PRIVATE_TIMEOUT")
    else:
        storage.read_mock.side_effect = lambda path: ("f" * 40, {"private": "PRIVATE_CONTENT"})
    with pytest.raises(runtime.RuntimeStateError) as error:
        state.save_cookies([COOKIE])
    assert "PRIVATE" not in str(error.value)
    attempts = storage.write_mock.call_count
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_unconfirmed"):
        state.save_journal(storage.path)
    assert storage.write_mock.call_count == attempts
    assert len(storage.writes) <= writes_before + 1


def test_marker_survives_interrupted_initialization_and_prevents_empty_retry(storage):
    original_write = storage.write
    def fail_snapshot(path, *args, **kwargs):
        if path == runtime.STATE_PATH:
            raise TimeoutError("PRIVATE_FAILURE")
        return original_write(path, *args, **kwargs)
    storage.write_mock.side_effect = fail_snapshot
    with pytest.raises(runtime.RuntimeStateError):
        initialize(storage)
    assert runtime.MARKER_PATH in storage.remote
    assert runtime.STATE_PATH not in storage.remote
    with pytest.raises(runtime.RuntimeStateError, match="runtime_already_initialized"):
        runtime.RuntimeState().initialize(ACCOUNT, storage.path.with_name("replacement.sqlite"))


@pytest.mark.parametrize("change", ["wrong_domain", "insecure", "unknown_field", "wrong_type",
                                   "specified_not_bool", "initial_dot_not_bool", "double_dot_domain"])
def test_untrusted_cookie_shapes_are_never_persisted(storage, change):
    state = initialize(storage)
    cookie = copy.deepcopy(COOKIE)
    if change == "wrong_domain":
        cookie["domain"] = "attacker.invalid"
    elif change == "double_dot_domain":
        cookie["domain"] = "..alditalk-kundenportal.de"
    elif change == "insecure":
        cookie["secure"] = False
    elif change == "unknown_field":
        cookie["token"] = "PRIVATE_TOKEN"
    elif change == "wrong_type":
        cookie["expires"] = True
    elif change == "specified_not_bool":
        cookie["domain_specified"] = "true"
    else:
        cookie["domain_initial_dot"] = 1
    before = len(storage.writes)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_cookies_invalid"):
        state.save_cookies([cookie])
    assert len(storage.writes) == before


def test_restore_refuses_overwrite_and_checkout_paths(storage, monkeypatch):
    state = initialize(storage)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_journal_already_exists"):
        state.restore_journal(storage.path)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(storage.path.parent))
    with pytest.raises(runtime.RuntimeStateError, match="runtime_journal_inside_checkout"):
        state.restore_journal(storage.path.with_name("checkout.sqlite"))


def test_snapshot_failure_poison_does_not_write_empty_replacement(storage):
    state = initialize(storage)
    storage.path.write_bytes(b"PRIVATE_CORRUPTION")
    before = storage.write_mock.call_count
    with pytest.raises(runtime.RuntimeStateError, match="runtime_journal_snapshot_failed"):
        state.save_journal(storage.path)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_unconfirmed"):
        state.save_cookies([])
    assert storage.write_mock.call_count == before


def test_two_loaded_writers_cannot_overwrite_newer_history(storage):
    first = initialize(storage)
    stale = runtime.RuntimeState().load(ACCOUNT)
    first.accept_refill()
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_write_failed"):
        stale.save_cookies([COOKIE])
    latest = runtime.RuntimeState().load(ACCOUNT)
    assert latest.refill_accepted is True
    assert latest.cookies == []


def test_snapshot_payload_size_limit_keeps_last_confirmed_state(storage, monkeypatch):
    state = initialize(storage)
    original = copy.deepcopy(storage.remote[runtime.STATE_PATH])
    monkeypatch.setattr(runtime, "MAX_PAYLOAD_BYTES", 1)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_snapshot_too_large"):
        state.save_cookies([])
    assert storage.remote[runtime.STATE_PATH] == original
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_unconfirmed"):
        state.accept_refill()


def test_unconfirmed_initialization_marker_never_creates_journal(storage):
    storage.read_mock.side_effect = [None, None, None]
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_unconfirmed"):
        initialize(storage)
    assert not storage.path.exists()
    assert runtime.STATE_PATH not in storage.remote


def test_restore_rejects_symlink_and_preserves_target(storage):
    state = initialize(storage)
    target = storage.path.with_name("private-target.txt")
    target.write_text("PRIVATE_EXISTING_DATA")
    link = storage.path.with_name("linked.sqlite")
    link.symlink_to(target)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_journal_path_invalid"):
        state.restore_journal(link)
    assert target.read_text() == "PRIVATE_EXISTING_DATA"


@pytest.mark.parametrize("domain,specified,initial_dot", [
    ("www.alditalk-kundenportal.de", False, False),
    (".alditalk-kundenportal.de", True, True),
    (".alditalk-kundenportal.de", True, False),
])
def test_cookie_scope_flags_survive_encrypted_roundtrip(storage, domain, specified, initial_dot):
    state = initialize(storage)
    cookie = dict(COOKIE, domain=domain, domain_specified=specified, domain_initial_dot=initial_dot)
    state.save_cookies([cookie])
    restored = runtime.RuntimeState().load(ACCOUNT)
    assert restored.cookies == [cookie]
    assert restored.cookies[0]["domain_specified"] is specified
    assert restored.cookies[0]["domain_initial_dot"] is initial_dot


def test_cookie_without_explicit_scope_flags_is_not_silently_promoted(storage):
    state = initialize(storage)
    cookie = dict(COOKIE)
    del cookie["domain_specified"]
    del cookie["domain_initial_dot"]
    before = len(storage.writes)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_cookies_invalid"):
        state.save_cookies([cookie])
    assert len(storage.writes) == before


def test_first_refill_authorization_survives_restart_without_claiming_acceptance(storage):
    state = initialize(storage)
    state.authorize_first_refill()
    restored = runtime.RuntimeState().load(ACCOUNT)
    assert restored.first_refill_authorized is True
    assert restored.refill_accepted is False
    restored.accept_refill()
    accepted = runtime.RuntimeState().load(ACCOUNT)
    assert accepted.first_refill_authorized is True
    assert accepted.refill_accepted is True


@pytest.mark.parametrize("value", [None, "true", 1, {}])
def test_first_refill_authorization_requires_explicit_boolean(storage, value):
    initialize(storage)
    sha, envelope = storage.remote[runtime.STATE_PATH]
    payload = json.loads(Fernet(storage.key).decrypt(envelope["ciphertext"].encode()))
    payload["first_refill_authorized"] = value
    envelope["ciphertext"] = Fernet(storage.key).encrypt(json.dumps(payload).encode()).decode()
    storage.remote[runtime.STATE_PATH] = (sha, envelope)
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_invalid"):
        runtime.RuntimeState().load(ACCOUNT)


def test_repeated_unchanged_cookies_and_full_journal_do_not_create_commits(storage):
    state = initialize(storage)
    before = storage.write_mock.call_count
    for _ in range(3):
        state.save_cookies([])
        state.save_journal(storage.path)
    assert storage.write_mock.call_count == before
    loaded = runtime.RuntimeState().load(ACCOUNT)
    restored_path = storage.path.with_name("restored.sqlite")
    loaded.restore_journal(restored_path)
    for _ in range(3):
        loaded.save_cookies([])
        loaded.save_journal(restored_path)
    assert storage.write_mock.call_count == before


def test_only_changed_cookie_journal_and_flags_are_committed(storage):
    state = initialize(storage)
    before = storage.write_mock.call_count
    state.save_cookies([COOKIE])
    assert storage.write_mock.call_count == before + 1
    state.save_cookies([COOKIE])
    assert storage.write_mock.call_count == before + 1
    db = Database(str(storage.path))
    operation = db.begin_recharge("alditalk", ACCOUNT)
    state.save_journal(storage.path)
    assert storage.write_mock.call_count == before + 2
    state.save_journal(storage.path)
    assert storage.write_mock.call_count == before + 2
    db.set_recharge_status(operation, "UNKNOWN")
    state.save_journal(storage.path)
    assert storage.write_mock.call_count == before + 3
    state.authorize_first_refill()
    state.authorize_first_refill()
    assert storage.write_mock.call_count == before + 4
    state.accept_refill()
    state.accept_refill()
    assert storage.write_mock.call_count == before + 5


def test_poisoned_instance_rejects_even_previously_confirmed_unchanged_payload(storage):
    state = initialize(storage)
    storage.write_mock.side_effect = TimeoutError("PRIVATE_WRITE_FAILURE")
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_write_failed"):
        state.save_cookies([COOKIE])
    attempts = storage.write_mock.call_count
    with pytest.raises(runtime.RuntimeStateError, match="runtime_state_unconfirmed"):
        state.save_cookies([])
    assert storage.write_mock.call_count == attempts
