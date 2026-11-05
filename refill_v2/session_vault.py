"""Encrypted, account-bound Playwright storage_state and credential files.

Fernet key comes from the process environment / a secret manager, NOT from a
committed .env file. Decrypted cookies never touch a temporary plaintext file.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import re
import tempfile

from cryptography.fernet import Fernet, InvalidToken

_ACCOUNT = re.compile(r"^[a-z][a-z0-9_-]{2,39}$")
_VERSION = 1


class SessionVault:
    def __init__(self, directory: str | Path, key: bytes, *,
                 max_age: timedelta = timedelta(hours=12)):
        if max_age <= timedelta(0):
            raise ValueError("positive session lifetime required")
        self._cipher = Fernet(key)
        self.directory = Path(directory).expanduser().absolute()
        self.max_age = max_age
        if self.directory.is_symlink():
            raise ValueError("vault symlinks not allowed")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix" and self.directory.stat().st_mode & 0o077:
            raise PermissionError("vault directory must be private (chmod 700)")

    @classmethod
    def from_environment(cls, directory: str | Path) -> "SessionVault":
        value = os.environ.get("REFILL_SESSION_FERNET_KEY")
        if not value:
            raise RuntimeError("REFILL_SESSION_FERNET_KEY is missing (fail closed)")
        return cls(directory, value.encode("ascii"))

    def _file(self, account_id: str, kind: str) -> Path:
        if not isinstance(account_id, str) or not _ACCOUNT.fullmatch(account_id):
            raise ValueError("invalid account alias")
        if re.search(r"\d{7,}", account_id):
            raise ValueError("alias may not include a phone number")
        return self.directory / f"{account_id}.{kind}.enc"

    def _write(self, file: Path, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        encrypted = self._cipher.encrypt(data)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="wb", dir=self.directory, prefix=".pending-",
                    delete=False) as stream:
                temporary = stream.name
                os.chmod(temporary, 0o600)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            if file.is_symlink():
                raise ValueError("vault target symlink rejected")
            os.replace(temporary, file)
            temporary = None
            if os.name == "posix":
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def _read(self, file: Path) -> dict | None:
        if file.is_symlink():
            raise ValueError("vault target symlink rejected")
        if not file.exists():
            return None
        if os.name == "posix" and file.stat().st_mode & 0o077:
            raise PermissionError("vault file must have mode 0600")
        raw = file.read_bytes()
        try:
            payload = json.loads(self._cipher.decrypt(raw))
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("encrypted vault data could not be validated") from exc
        if not isinstance(payload, dict) or payload.get("version") != _VERSION:
            raise ValueError("unknown vault version")
        return payload

    def save_credentials(self, account_id: str, username: str,
                         password: str) -> None:
        if not username or not password:
            raise ValueError("credentials required")
        self._write(self._file(account_id, "credentials"), {
            "version": _VERSION, "account_id": account_id,
            "username": username, "password": password,
        })

    def load_credentials(self, account_id: str) -> tuple[str, str] | None:
        payload = self._read(self._file(account_id, "credentials"))
        if payload is None:
            return None
        if payload.get("account_id") != account_id:
            raise ValueError("vault account binding mismatch")
        username, password = payload.get("username"), payload.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValueError("invalid credential payload")
        return username, password

    async def save_session(self, account_id: str, context) -> None:
        # No path=... argument: Playwright returns a dictionary in memory.
        storage_state = await context.storage_state(indexed_db=True)
        self._write(self._file(account_id, "session"), {
            "version": _VERSION, "account_id": account_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "storage_state": storage_state,
        })

    def load_session(self, account_id: str) -> dict | None:
        payload = self._read(self._file(account_id, "session"))
        if payload is None:
            return None
        if payload.get("account_id") != account_id:
            raise ValueError("vault account binding mismatch")
        try:
            saved_at = datetime.fromisoformat(payload["saved_at"])
            if saved_at.tzinfo is None:
                raise ValueError("session time not timezone-aware")
            age = datetime.now(timezone.utc) - saved_at.astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid session timestamp") from exc
        if age < timedelta(seconds=-5) or age > self.max_age:
            return None  # Never assume a session is still authenticated.
        state = payload.get("storage_state")
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) \
                or not isinstance(state.get("origins"), list):
            raise ValueError("invalid Playwright storage state")
        return state
