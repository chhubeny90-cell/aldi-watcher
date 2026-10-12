"""Public-safe durable state for GitHub-hosted ALDI live refill runs.

The public state branch stores only random recharge operation IDs, the
non-terminal states PENDING/UNKNOWN, and an optional authentication retry time.
Phone numbers, credentials, tariffs, allowances, SQLite bytes and provider error
text never leave the runner.
"""

import base64
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from core.aldi_http_login import phone_identifier
from core.database import Database


STATE_VERSION = 2
MAX_UNRESOLVED = 16
DEFAULT_BRANCH = "aldi-watcher-state"
DEFAULT_PATH = ".aldi-state/profile-1.json"
_ALLOWED_STATUSES = {"PENDING", "UNKNOWN"}


def _repo():
    value = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" not in value:
        raise RuntimeError("github_repository_unavailable")
    return value


def _token():
    value = os.environ.get("GITHUB_TOKEN", "").strip()
    if not value:
        raise RuntimeError("github_token_unavailable")
    return value


def _branch():
    return os.environ.get("ALDI_STATE_BRANCH", DEFAULT_BRANCH).strip() or DEFAULT_BRANCH


def _state_path():
    return os.environ.get("ALDI_STATE_PATH", DEFAULT_PATH).strip() or DEFAULT_PATH


def _headers():
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _url(path: str) -> str:
    root = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    return f"{root}/repos/{_repo()}/{path.lstrip('/')}"


def _request(method: str, path: str, *, json_body=None, expected=(200,)):
    response = requests.request(
        method, _url(path), headers=_headers(), json=json_body, timeout=20,
    )
    if response.status_code not in expected:
        raise RuntimeError(f"github_state_http_{response.status_code}")
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def _ensure_branch():
    branch = _branch()
    encoded = quote(branch, safe="")
    response = requests.get(
        _url(f"git/ref/heads/{encoded}"), headers=_headers(), timeout=20,
    )
    if response.status_code == 200:
        return
    if response.status_code != 404:
        raise RuntimeError(f"github_state_ref_http_{response.status_code}")
    base_sha = os.environ.get("GITHUB_SHA", "").strip()
    if len(base_sha) < 7:
        raise RuntimeError("github_sha_unavailable")
    create = requests.post(
        _url("git/refs"), headers=_headers(),
        json={"ref": f"refs/heads/{branch}", "sha": base_sha}, timeout=20,
    )
    if create.status_code not in {201, 422}:
        raise RuntimeError(f"github_state_ref_create_http_{create.status_code}")


def _validate_operation(operation):
    if not isinstance(operation, dict) or set(operation) != {"recharge_id", "status"}:
        raise RuntimeError("github_state_schema_invalid")
    recharge_id = operation.get("recharge_id")
    status = operation.get("status")
    if not isinstance(recharge_id, str) or status not in _ALLOWED_STATUSES:
        raise RuntimeError("github_state_schema_invalid")
    try:
        parsed = uuid.UUID(recharge_id)
    except (ValueError, AttributeError):
        raise RuntimeError("github_state_schema_invalid") from None
    if str(parsed) != recharge_id:
        raise RuntimeError("github_state_schema_invalid")
    return {"recharge_id": recharge_id, "status": status}


def _validate_retry_after(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise RuntimeError("github_state_schema_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeError("github_state_schema_invalid") from None
    if parsed.tzinfo is None:
        raise RuntimeError("github_state_schema_invalid")
    parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _empty_state():
    return {"version": STATE_VERSION, "unresolved": [], "auth_retry_after": None}


def _parse_state(content: bytes):
    if not isinstance(content, bytes) or len(content) > 65536:
        raise RuntimeError("github_state_content_invalid")
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("github_state_content_invalid") from None
    if not isinstance(payload, dict):
        raise RuntimeError("github_state_schema_invalid")

    # Version 1 contained only unresolved operation guards. Accept it once and
    # upgrade in memory so a deployment can roll forward without losing a guard.
    if payload.get("version") == 1 and set(payload) == {"version", "unresolved"}:
        payload = {
            "version": STATE_VERSION,
            "unresolved": payload.get("unresolved"),
            "auth_retry_after": None,
        }

    if (set(payload) != {"version", "unresolved", "auth_retry_after"}
            or payload.get("version") != STATE_VERSION
            or not isinstance(payload.get("unresolved"), list)
            or len(payload["unresolved"]) > MAX_UNRESOLVED):
        raise RuntimeError("github_state_schema_invalid")
    operations = [_validate_operation(item) for item in payload["unresolved"]]
    ids = [item["recharge_id"] for item in operations]
    if len(ids) != len(set(ids)):
        raise RuntimeError("github_state_schema_invalid")
    return {
        "version": STATE_VERSION,
        "unresolved": operations,
        "auth_retry_after": _validate_retry_after(payload.get("auth_retry_after")),
    }


def _encode_state(operations, auth_retry_after=None):
    validated = [_validate_operation(item) for item in operations]
    if len(validated) > MAX_UNRESOLVED:
        raise RuntimeError("too_many_unresolved_operations")
    payload = {
        "version": STATE_VERSION,
        "unresolved": validated,
        "auth_retry_after": _validate_retry_after(auth_retry_after),
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _get_state():
    _ensure_branch()
    branch = quote(_branch(), safe="")
    path = quote(_state_path(), safe="/")
    response = requests.get(
        _url(f"contents/{path}?ref={branch}"), headers=_headers(), timeout=20,
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RuntimeError(f"github_state_read_http_{response.status_code}")
    payload = response.json()
    if payload.get("type") != "file" or not payload.get("sha"):
        raise RuntimeError("github_state_metadata_invalid")
    try:
        content = base64.b64decode(payload.get("content", ""), validate=False)
    except Exception as exc:
        raise RuntimeError("github_state_content_invalid") from exc
    return payload["sha"], _parse_state(content)


def _put_state(state, current_sha=None, message="Persist ALDI refill guard state"):
    content = _encode_state(state["unresolved"], state.get("auth_retry_after"))
    payload = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": _branch(),
    }
    if current_sha is not None:
        payload["sha"] = current_sha
    state_path = quote(_state_path(), safe="/")
    _request("PUT", f"contents/{state_path}", json_body=payload, expected=(200, 201))


def _snapshot_unresolved(journal_path):
    path = Path(journal_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError("journal_path_invalid")
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT recharge_id, status FROM recharges "
            "WHERE status IN ('PENDING','UNKNOWN') ORDER BY created_at"
        ).fetchall()
    return [_validate_operation({"recharge_id": row[0], "status": row[1]}) for row in rows]


def sync_journal(journal_path):
    operations = _snapshot_unresolved(journal_path)
    current = _get_state()
    state = _empty_state() if current is None else current[1]
    state["unresolved"] = operations
    _put_state(state, current[0] if current is not None else None)


def auth_backoff_active(now=None):
    current = _get_state()
    if current is None or current[1].get("auth_retry_after") is None:
        return False
    retry = datetime.fromisoformat(
        current[1]["auth_retry_after"].replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise RuntimeError("naive_auth_backoff_reference")
    return reference.astimezone(timezone.utc) < retry


def set_auth_backoff(hours=6, now=None):
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours <= 0 or hours > 24:
        raise RuntimeError("invalid_auth_backoff")
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise RuntimeError("naive_auth_backoff_reference")
    retry = reference.astimezone(timezone.utc) + timedelta(hours=float(hours))
    retry_text = retry.isoformat().replace("+00:00", "Z")
    current = _get_state()
    state = _empty_state() if current is None else current[1]
    state["auth_retry_after"] = retry_text
    _put_state(
        state,
        current[0] if current is not None else None,
        message="Back off ALDI authentication after failed login",
    )
    return retry_text


def restore_journal(journal_path, account):
    """Rehydrate unresolved guard rows using the account only inside this runner."""
    path = Path(journal_path)
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("journal_path_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    current = _get_state()
    state = _empty_state() if current is None else current[1]
    operations = state["unresolved"]
    canonical_account = phone_identifier(account)
    db = Database(str(path))
    now = datetime.now().isoformat()
    with db._connect() as conn:
        for operation in operations:
            conn.execute(
                "INSERT INTO recharges "
                "(recharge_id, provider, username, status, error_message, created_at, updated_at) "
                "VALUES (?, 'alditalk', ?, ?, NULL, ?, ?)",
                (operation["recharge_id"], canonical_account, operation["status"], now, now),
            )
    path.chmod(0o600)

    if current is None:
        sync_journal(path)
        return "initialized"
    return "restored"
