"""Owner-only Fernet storage for browser state and encrypted incident bytes.

Additive utility: does not replace core.security.SecurityManager or the
existing recharge journal. Key creation is explicit and NEVER overwrites a key.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


def _private_parent(target: Path) -> None:
    """Require a private, non-symlink destination directory."""
    if ".." in target.parts or not target.name:
        raise ValueError("unsafe_storage_path")
    parent = target.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for ancestor in (parent, *parent.parents):
        if ancestor.is_symlink():
            raise ValueError("storage_symlink_not_allowed")
    if not parent.is_dir():
        raise ValueError("storage_parent_not_directory")
    if os.name == "posix" and (parent.stat().st_mode & 0o077):
        raise PermissionError("storage_directory_not_private")


def write_restricted_atomic(target: str | Path, data: bytes) -> None:
    """Atomically replace an encrypted file, mode 0600 from creation.

    The caller must encrypt before calling this function. No unencrypted
    session state or incident bytes are ever written to disk by this module.
    """
    target = Path(target)
    if not isinstance(data, bytes):
        raise TypeError("data_must_be_bytes")
    _private_parent(target)
    if target.is_symlink():
        raise ValueError("storage_symlink_not_allowed")
    if target.exists() and not target.is_file():
        raise ValueError("storage_target_not_regular_file")

    fd, temporary = tempfile.mkstemp(prefix=".encrypted-", dir=str(target.parent))
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        if os.name == "posix":
            directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_private_key(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("key_symlink_not_allowed")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError("key_file_not_regular")
        if os.name == "posix" and (st.st_mode & 0o077):
            raise PermissionError("key_permissions_not_private")
        return stream.read().strip()


class SessionVault:
    def __init__(self, key: bytes):
        self.cipher = Fernet(key)

    @classmethod
    def from_environment(cls) -> "SessionVault":
        key = os.environ.get("WATCHER_FERNET_KEY")
        if not key:
            raise RuntimeError("WATCHER_FERNET_KEY_missing")
        return cls(key.encode("ascii"))

    @classmethod
    def from_keyfile(
        cls,
        keyfile_path: str | Path = "private/keys/master.key",
        *,
        create: bool = False,
    ) -> "SessionVault":
        """Load an existing protected key.

        Explicit create=True is for initial setup only. A missing key never
        silently gets regenerated on subsequent watcher starts.
        """
        path = Path(keyfile_path)
        _private_parent(path)
        if create:
            key = Fernet.generate_key()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(key)
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return cls(_read_private_key(path))

    def encrypt_bytes(self, path: str | Path, plaintext: bytes) -> None:
        if not isinstance(plaintext, bytes):
            raise TypeError("plaintext_must_be_bytes")
        write_restricted_atomic(path, self.cipher.encrypt(plaintext))

    def decrypt_bytes(self, path: str | Path) -> bytes:
        return self.cipher.decrypt(Path(path).read_bytes())

    def save(self, path: str | Path, storage_state: dict[str, Any]) -> None:
        if not isinstance(storage_state, dict):
            raise TypeError("storage_state_must_be_mapping")
        payload = json.dumps(
            storage_state, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.encrypt_bytes(path, payload)

    def load(self, path: str | Path) -> dict[str, Any]:
        value = json.loads(self.decrypt_bytes(path))
        if not isinstance(value, dict):
            raise ValueError("storage_state_not_mapping")
        return value
