"""SessionVault only: no browser, no provider network, no recharge side effects."""

import os

import pytest
from cryptography.fernet import Fernet, InvalidToken

from core.crypto import SessionVault, write_restricted_atomic


def test_initial_creation_requires_explicit_opt_in_and_never_rotates(tmp_path):
    key_path = tmp_path / "private" / "keys" / "master.key"
    with pytest.raises(FileNotFoundError):
        SessionVault.from_keyfile(key_path)
    assert not key_path.exists()

    first = SessionVault.from_keyfile(key_path, create=True)
    original_key = key_path.read_bytes()
    assert original_key
    with pytest.raises(FileExistsError):
        SessionVault.from_keyfile(key_path, create=True)
    assert key_path.read_bytes() == original_key
    assert first.cipher.decrypt(first.cipher.encrypt(b"probe")) == b"probe"

    if os.name == "posix":
        assert key_path.stat().st_mode & 0o777 == 0o600
        assert key_path.parent.stat().st_mode & 0o777 == 0o700


def test_session_ciphertext_round_trip_no_plaintext_on_disk(tmp_path):
    vault = SessionVault(Fernet.generate_key())
    session_path = tmp_path / "sessions" / "account_a.enc"
    state = {"cookies": [{"name": "test", "value": "private-cookie-sentinel"}], "origins": []}
    vault.save(session_path, state)
    assert vault.load(session_path) == state
    assert b"private-cookie-sentinel" not in session_path.read_bytes()
    if os.name == "posix":
        assert session_path.stat().st_mode & 0o777 == 0o600


def test_incident_bytes_encrypted_in_memory(tmp_path):
    vault = SessionVault(Fernet.generate_key())
    incident_path = tmp_path / "incidents" / "incident.png.enc"
    vault.encrypt_bytes(incident_path, b"SECRET_SCREENSHOT_CONTENT")
    assert b"SECRET_SCREENSHOT_CONTENT" not in incident_path.read_bytes()
    assert vault.decrypt_bytes(incident_path) == b"SECRET_SCREENSHOT_CONTENT"


def test_wrong_key_fails_without_writing_or_rotating(tmp_path):
    session_path = tmp_path / "sessions" / "account_a.enc"
    SessionVault(Fernet.generate_key()).save(session_path, {"cookies": []})
    before = session_path.read_bytes()
    with pytest.raises(InvalidToken):
        SessionVault(Fernet.generate_key()).load(session_path)
    assert session_path.read_bytes() == before


def test_environment_key_required_and_never_generated(monkeypatch):
    monkeypatch.delenv("WATCHER_FERNET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="WATCHER_FERNET_KEY_missing"):
        SessionVault.from_environment()
    key = Fernet.generate_key()
    monkeypatch.setenv("WATCHER_FERNET_KEY", key.decode())
    assert SessionVault.from_environment().cipher.decrypt(Fernet(key).encrypt(b"ok")) == b"ok"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permission enforcement")
def test_insecure_or_linked_key_rejected(tmp_path):
    key = tmp_path / "master.key"
    key.write_bytes(Fernet.generate_key())
    key.chmod(0o644)
    with pytest.raises(PermissionError, match="key_permissions_not_private"):
        SessionVault.from_keyfile(key)

    key.chmod(0o600)
    linked = tmp_path / "link.key"
    linked.symlink_to(key)
    with pytest.raises(ValueError, match="key_symlink_not_allowed"):
        SessionVault.from_keyfile(linked)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permission enforcement")
def test_insecure_directory_and_symlinked_storage_rejected(tmp_path):
    vault = SessionVault(Fernet.generate_key())
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(PermissionError, match="storage_directory_not_private"):
        vault.save(public / "account_a.enc", {"cookies": []})

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(private, target_is_directory=True)
    with pytest.raises(ValueError, match="storage_symlink_not_allowed"):
        vault.save(linked / "account_a.enc", {"cookies": []})


def test_atomic_replace_failure_preserves_existing_ciphertext(tmp_path, monkeypatch):
    target = tmp_path / "account_a.enc"
    before = b"old encrypted record"
    write_restricted_atomic(target, before)

    def fail_replace(src, dst):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated filesystem failure"):
        write_restricted_atomic(target, b"new encrypted record")

    assert target.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["account_a.enc"]


def test_write_does_not_follow_target_symlink(tmp_path):
    target = tmp_path / "other.enc"
    target.write_bytes(b"unchanged")
    link = tmp_path / "link.enc"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="storage_symlink_not_allowed"):
        write_restricted_atomic(link, b"ciphertext")
    assert target.read_bytes() == b"unchanged"
