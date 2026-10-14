"""Encrypted durable recharge journal backed by a dedicated GitHub branch.

The public repository stores only a Fernet ciphertext. The plaintext SQLite file
exists only on the runner with mode 0600. Every provider-relevant state mutation
is persisted through GitHub's Contents API using the previous blob SHA as a
compare-and-set token. A stale SHA therefore fails before a caller can treat a
PENDING reservation as durable.
"""

import base64
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

import requests
from cryptography.fernet import Fernet, InvalidToken

from core.database import Database, RechargeLockedError


DEFAULT_STATE_BRANCH = "runtime-state"
DEFAULT_STATE_PATH = ".runtime/aldi-journal.enc"
MAX_ENCRYPTED_STATE_BYTES = 2 * 1024 * 1024


class GitHubJournal(Database):
    """SQLite Database whose committed mutations are mirrored as ciphertext."""

    def __init__(
        self,
        repository: str,
        token: str,
        key: str,
        *,
        branch: str = DEFAULT_STATE_BRANCH,
        remote_path: str = DEFAULT_STATE_PATH,
        session=None,
        temp_dir=None,
    ):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
            raise RuntimeError("github_journal_repository_invalid")
        if not token:
            raise RuntimeError("github_journal_token_missing")
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch or "") or ".." in branch:
            raise RuntimeError("github_journal_branch_invalid")
        if (not remote_path or remote_path.startswith("/") or ".." in Path(remote_path).parts):
            raise RuntimeError("github_journal_path_invalid")
        try:
            self._fernet = Fernet((key or "").strip().encode())
        except Exception as exc:
            raise RuntimeError("github_journal_key_invalid") from exc

        self.repository = repository
        self.branch = branch
        self.remote_path = remote_path
        self._remote_sha = None
        self._session = session or requests.Session()
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        encoded_path = quote(remote_path, safe="/")
        self._url = f"https://api.github.com/repos/{repository}/contents/{encoded_path}"

        directory = Path(temp_dir or os.getenv("RUNNER_TEMP") or tempfile.gettempdir())
        if not directory.is_dir():
            raise RuntimeError("github_journal_temp_dir_missing")
        fd, local = tempfile.mkstemp(prefix="aldi-journal-", suffix=".sqlite", dir=directory)
        os.close(fd)
        self._local_path = Path(local)
        if os.name == "posix":
            self._local_path.chmod(0o600)

        try:
            remote = self._fetch_remote(allow_missing=True)
            if remote is not None:
                self._install_plaintext(remote[1])
                self._remote_sha = remote[0]
            super().__init__(str(self._local_path))
            if remote is None:
                self._sync_remote(create=True)
        except Exception:
            self.cleanup()
            raise

    @classmethod
    def from_environment(cls, **kwargs):
        key = os.getenv("ALDI_STATE_KEY") or os.getenv("CREDENTIAL_ENCRYPTION_KEY") or ""
        return cls(
            os.getenv("GITHUB_REPOSITORY", ""),
            os.getenv("GITHUB_TOKEN", ""),
            key,
            branch=os.getenv("ALDI_STATE_BRANCH", DEFAULT_STATE_BRANCH),
            remote_path=os.getenv("ALDI_STATE_PATH", DEFAULT_STATE_PATH),
            **kwargs,
        )

    def _fetch_remote(self, *, allow_missing=False):
        try:
            response = self._session.get(
                self._url,
                headers=self._headers,
                params={"ref": self.branch},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise RuntimeError("github_journal_read_failed") from exc
        if response.status_code == 404 and allow_missing:
            return None
        if response.status_code != 200:
            raise RuntimeError("github_journal_read_failed")
        try:
            payload = response.json()
            sha = payload["sha"]
            encoded = payload["content"].replace("\n", "")
            ciphertext = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise RuntimeError("github_journal_response_invalid") from exc
        if not isinstance(sha, str) or not sha or len(ciphertext) > MAX_ENCRYPTED_STATE_BYTES:
            raise RuntimeError("github_journal_response_invalid")
        try:
            plaintext = self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise RuntimeError("github_journal_decryption_failed") from exc
        if not plaintext.startswith(b"SQLite format 3\x00"):
            raise RuntimeError("github_journal_plaintext_invalid")
        return sha, plaintext

    def _install_plaintext(self, plaintext: bytes):
        if not plaintext.startswith(b"SQLite format 3\x00"):
            raise RuntimeError("github_journal_plaintext_invalid")
        temporary = self._local_path.with_suffix(".restore")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(plaintext)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        os.replace(temporary, self._local_path)
        if os.name == "posix":
            self._local_path.chmod(0o600)

    def _sync_remote(self, *, create=False):
        plaintext = self._local_path.read_bytes()
        if not plaintext.startswith(b"SQLite format 3\x00"):
            raise RuntimeError("github_journal_plaintext_invalid")
        ciphertext = self._fernet.encrypt(plaintext)
        payload = {
            "message": "Update encrypted ALDI runtime state",
            "content": base64.b64encode(ciphertext).decode(),
            "branch": self.branch,
        }
        if not create:
            if not self._remote_sha:
                raise RuntimeError("github_journal_sha_missing")
            payload["sha"] = self._remote_sha
        try:
            response = self._session.put(
                self._url,
                headers=self._headers,
                json=payload,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise RechargeLockedError("github_journal_write_unconfirmed") from exc
        if response.status_code in {409, 422}:
            raise RechargeLockedError("github_journal_compare_and_set_conflict")
        if response.status_code not in {200, 201}:
            raise RechargeLockedError("github_journal_write_unconfirmed")
        try:
            new_sha = response.json()["content"]["sha"]
        except Exception as exc:
            raise RechargeLockedError("github_journal_write_unconfirmed") from exc
        if not isinstance(new_sha, str) or not new_sha:
            raise RechargeLockedError("github_journal_write_unconfirmed")
        self._remote_sha = new_sha

    def _refresh_remote(self):
        remote = self._fetch_remote(allow_missing=False)
        if remote[0] == self._remote_sha:
            return
        self._install_plaintext(remote[1])
        self._remote_sha = remote[0]
        # Re-run schema initialization/validation after accepting a newer durable
        # state. This may migrate an old compatible journal but never invents a
        # missing encrypted remote state.
        self._init_schema()

    def begin_recharge(self, provider: str, username: str, recent_success_guard_seconds: float = 0) -> str:
        self._refresh_remote()
        recharge_id = super().begin_recharge(
            provider,
            username,
            recent_success_guard_seconds=recent_success_guard_seconds,
        )
        # Critical invariant: return the reservation ID only after remote PENDING
        # is durably committed. A failed CAS therefore prevents the provider click.
        self._sync_remote()
        return recharge_id

    def set_recharge_status(self, recharge_id: str, status: str, error_message=None):
        self._refresh_remote()
        result = super().set_recharge_status(recharge_id, status, error_message)
        self._sync_remote()
        return result

    def get_unresolved_recharges(self, provider=None, username=None):
        self._refresh_remote()
        return super().get_unresolved_recharges(provider, username)

    def cleanup(self):
        """Remove only ephemeral plaintext/lock files from the runner."""
        path = getattr(self, "_local_path", None)
        if path is None:
            return
        for lock in path.parent.glob(path.name + ".*.lock"):
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
        for candidate in (path, path.with_suffix(".restore")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
