"""Encrypted hosted ALDI session and complete journal, with confirmed CAS writes.

Only ciphertext and a non-identifying initialization marker leave the runner.
A missing or unreadable initialized journal is never replaced with empty history.
"""
import base64
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from cryptography.fernet import Fernet

from core.aldi_http_login import ALLOWED_HOSTS, phone_identifier
from core.database import Database
from github_hardening_state import _read_json, _write_json
from github_journal_state import consistent_mail_snapshot


STATE_PATH = ".aldi-state/profile-1.runtime.json"
MARKER_PATH = ".aldi-state/profile-1.runtime-initialized.json"
MAX_PAYLOAD_BYTES = 512 * 1024
_MARKER = {"version": 1, "initialized": True}
_COOKIE_DOMAINS = ALLOWED_HOSTS | {host.removeprefix("www.") for host in ALLOWED_HOSTS}


class RuntimeStateError(RuntimeError):
    """Fixed local codes only; never include private or upstream text."""


def _account(value):
    try:
        return phone_identifier(value)
    except Exception:
        raise RuntimeStateError("runtime_account_invalid") from None


def _journal_path(value, *, exists):
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink() or not path.parent.is_dir()
            or path.parent.is_symlink() or path.parent.stat().st_mode & 0o077):
        raise RuntimeStateError("runtime_journal_path_invalid")
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        try:
            path.resolve().relative_to(Path(workspace).resolve())
        except ValueError:
            pass
        else:
            raise RuntimeStateError("runtime_journal_inside_checkout")
    if exists:
        if not path.is_file() or path.stat().st_mode & 0o777 != 0o600:
            raise RuntimeStateError("runtime_journal_unavailable")
    elif path.exists():
        raise RuntimeStateError("runtime_journal_already_exists")
    return path


def _validate_database(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA trusted_schema=OFF")
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeStateError("runtime_journal_invalid")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(recharges)")}
        if not {"recharge_id", "provider", "username", "status", "created_at", "updated_at"}.issubset(columns):
            raise RuntimeStateError("runtime_journal_invalid")


def _journal_bytes(path):
    path = _journal_path(path, exists=True)
    with tempfile.TemporaryDirectory(prefix="aldi-runtime-snapshot-") as directory:
        target = Path(directory) / "snapshot.sqlite"
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        # SQLite backup includes committed WAL content, unlike copying the file.
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(str(target)) as backup:
                source.backup(backup)
        _validate_database(target)
        if target.stat().st_size > MAX_PAYLOAD_BYTES:
            raise RuntimeStateError("runtime_snapshot_too_large")
        return target.read_bytes()


def _validate_cookies(cookies):
    if not isinstance(cookies, list) or len(cookies) > 128:
        raise RuntimeStateError("runtime_cookies_invalid")
    for cookie in cookies:
        if not isinstance(cookie, dict) or set(cookie) != {
                "name", "value", "domain", "path", "secure", "expires", "rest",
                "domain_specified", "domain_initial_dot"}:
            raise RuntimeStateError("runtime_cookies_invalid")
        if (not all(isinstance(cookie[key], str) for key in ("name", "value", "domain", "path"))
                or not cookie["name"] or not cookie["path"].startswith("/")
                or cookie["domain"].removeprefix(".").lower() not in _COOKIE_DOMAINS
                or cookie["secure"] is not True
                or type(cookie["domain_specified"]) is not bool
                or type(cookie["domain_initial_dot"]) is not bool
                or not (cookie["expires"] is None or type(cookie["expires"]) is int)
                or not isinstance(cookie["rest"], dict)
                or len(cookie["rest"]) > 16
                or any(len(cookie[key]) > 16384 for key in ("name", "value", "domain", "path"))):
            raise RuntimeStateError("runtime_cookies_invalid")
        for key, value in cookie["rest"].items():
            if not isinstance(key, str) or len(key) > 128 or not (
                    value is None or isinstance(value, str) and len(value) <= 1024):
                raise RuntimeStateError("runtime_cookies_invalid")
    return copy.deepcopy(cookies)


class RuntimeState:
    def __init__(self, key=None):
        try:
            self._fernet = Fernet(key if key is not None else
                                  os.environ["ALDI_STATE_ENCRYPTION_KEY"].strip().encode("ascii"))
        except Exception:
            raise RuntimeStateError("runtime_encryption_key_required") from None
        self._sha = None
        self._payload = None
        self._confirmed_bytes = None
        self._poisoned = False

    def _usable(self):
        if self._poisoned:
            raise RuntimeStateError("runtime_state_unconfirmed")

    def _loaded(self):
        self._usable()
        if self._payload is None:
            raise RuntimeStateError("runtime_state_not_loaded")

    @property
    def cookies(self):
        self._loaded()
        return copy.deepcopy(self._payload["cookies"])

    @property
    def refill_accepted(self):
        self._loaded()
        return self._payload["refill_accepted"]

    @property
    def first_refill_authorized(self):
        self._loaded()
        return self._payload["first_refill_authorized"]

    def _decode(self, envelope, account):
        try:
            if (not isinstance(envelope, dict) or set(envelope) != {"version", "ciphertext"}
                    or type(envelope["version"]) is not int or envelope["version"] != 1
                    or not isinstance(envelope["ciphertext"], str)
                    or len(envelope["ciphertext"]) > MAX_PAYLOAD_BYTES * 2):
                raise ValueError()
            raw = self._fernet.decrypt(envelope["ciphertext"].encode("ascii"))
            if len(raw) > MAX_PAYLOAD_BYTES:
                raise ValueError()
            payload = json.loads(raw)
            if (not isinstance(payload, dict) or set(payload) != {
                    "version", "account", "cookies", "journal", "refill_accepted",
                    "first_refill_authorized"}
                    or type(payload["version"]) is not int or payload["version"] != 1
                    or payload["account"] != account
                    or type(payload["refill_accepted"]) is not bool
                    or type(payload["first_refill_authorized"]) is not bool
                    or not isinstance(payload["journal"], str)):
                raise ValueError()
            _validate_cookies(payload["cookies"])
            journal = base64.b64decode(payload["journal"], validate=True)
            if not journal.startswith(b"SQLite format 3\x00"):
                raise ValueError()
            with tempfile.TemporaryDirectory(prefix="aldi-runtime-validate-") as directory:
                path = Path(directory) / "journal.sqlite"
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(journal)
                _validate_database(path)
            return payload
        except Exception:
            raise RuntimeStateError("runtime_state_invalid") from None

    def load(self, account):
        self._usable()
        if self._payload is not None:
            raise RuntimeStateError("runtime_state_already_loaded")
        account = _account(account)
        try:
            marker = _read_json(MARKER_PATH)
            current = _read_json(STATE_PATH)
            if marker is None or marker[1] != _MARKER:
                raise RuntimeStateError("runtime_initialization_required")
            if current is None:
                raise RuntimeStateError("runtime_initialized_state_missing")
            self._payload = self._decode(current[1], account)
            self._sha = current[0]
            self._confirmed_bytes = self._canonical_bytes()
            return self
        except RuntimeStateError:
            self._poisoned = True
            raise
        except Exception:
            self._poisoned = True
            raise RuntimeStateError("runtime_state_read_failed") from None

    def initialize(self, account, journal_path):
        self._usable()
        if self._payload is not None:
            raise RuntimeStateError("runtime_state_already_loaded")
        account = _account(account)
        path = _journal_path(journal_path, exists=False)
        try:
            if _read_json(MARKER_PATH) is not None or _read_json(STATE_PATH) is not None:
                raise RuntimeStateError("runtime_already_initialized")
            _, events, journal = consistent_mail_snapshot()
            if (journal is None or journal[1]["unresolved"] or any(
                    event["phase"] in {"IN_FLIGHT", "QUARANTINED_UNKNOWN"}
                    for event in events.values())):
                raise RuntimeStateError("runtime_legacy_state_blocked")
            # The irreversible marker prevents a later missing snapshot from
            # becoming a blank replacement journal, including after failed init.
            _write_json(MARKER_PATH, _MARKER, None, message="Initialize encrypted ALDI runtime")
            marker = _read_json(MARKER_PATH)
            if marker is None or marker[1] != _MARKER:
                raise RuntimeStateError("runtime_state_unconfirmed")
            Database(str(path))
            self._payload = {"version": 1, "account": account, "cookies": [],
                             "journal": base64.b64encode(_journal_bytes(path)).decode("ascii"),
                             "refill_accepted": False, "first_refill_authorized": False}
            self._persist()
            return self
        except RuntimeStateError:
            self._poisoned = True
            raise
        except Exception:
            self._poisoned = True
            raise RuntimeStateError("runtime_initialization_failed") from None

    def _persist(self):
        self._loaded()
        try:
            raw = self._canonical_bytes()
            if len(raw) > MAX_PAYLOAD_BYTES:
                raise RuntimeStateError("runtime_snapshot_too_large")
            # Fernet randomizes every encryption. Skip unchanged confirmed
            # contents rather than committing a new ciphertext on every poll.
            if raw == self._confirmed_bytes:
                return
            envelope = {"version": 1, "ciphertext": self._fernet.encrypt(raw).decode("ascii")}
            _write_json(STATE_PATH, envelope, self._sha, message="Persist encrypted ALDI runtime")
            current = _read_json(STATE_PATH)
            if current is None or current[1] != envelope:
                raise RuntimeStateError("runtime_state_unconfirmed")
            self._sha = current[0]
            self._confirmed_bytes = raw
        except RuntimeStateError:
            self._poisoned = True
            raise
        except Exception:
            self._poisoned = True
            raise RuntimeStateError("runtime_state_write_failed") from None

    def _canonical_bytes(self):
        return json.dumps(self._payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    def restore_journal(self, journal_path):
        self._loaded()
        path = _journal_path(journal_path, exists=False)
        try:
            raw = base64.b64decode(self._payload["journal"], validate=True)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            _validate_database(path)
            return Database(str(path))
        except Exception:
            raise RuntimeStateError("runtime_journal_restore_failed") from None

    def save_journal(self, journal_path):
        self._loaded()
        try:
            self._payload["journal"] = base64.b64encode(_journal_bytes(journal_path)).decode("ascii")
            self._persist()
        except RuntimeStateError:
            self._poisoned = True
            raise
        except Exception:
            self._poisoned = True
            raise RuntimeStateError("runtime_journal_snapshot_failed") from None

    def save_cookies(self, cookies):
        self._loaded()
        self._payload["cookies"] = _validate_cookies(cookies)
        self._persist()

    def accept_refill(self):
        self._loaded()
        self._payload["refill_accepted"] = True
        self._persist()

    def authorize_first_refill(self):
        self._loaded()
        self._payload["first_refill_authorized"] = True
        self._persist()
