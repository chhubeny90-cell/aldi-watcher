"""Encrypted durable journal storage for GitHub-hosted live refill runs.

Only ciphertext is stored in the public repository. The key is provided through
an Actions secret and never written to disk or logs.
"""

import base64
import hashlib
import os
import secrets
from pathlib import Path
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.database import Database


MAGIC = b"ALDIJ1\x00"
DEFAULT_BRANCH = "aldi-watcher-state"
DEFAULT_PATH = ".aldi-state/journal.enc"


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


def _secret():
    value = os.environ.get("ALDI_JOURNAL_KEY", "")
    if len(value) < 20:
        raise RuntimeError("journal_key_unavailable")
    return value.encode("utf-8")


def _branch():
    return os.environ.get("ALDI_STATE_BRANCH", DEFAULT_BRANCH).strip() or DEFAULT_BRANCH


def _state_path():
    return os.environ.get("ALDI_STATE_PATH", DEFAULT_PATH).strip() or DEFAULT_PATH


def _aad():
    return f"{_repo()}:{_branch()}:{_state_path()}:v1".encode("utf-8")


def _key():
    return hashlib.sha256(b"aldi-journal-v1\x00" + _secret()).digest()


def encrypt_bytes(data: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, data, _aad())
    return MAGIC + nonce + ciphertext


def decrypt_bytes(blob: bytes) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) <= len(MAGIC) + 12:
        raise RuntimeError("journal_ciphertext_invalid")
    nonce = blob[len(MAGIC):len(MAGIC) + 12]
    ciphertext = blob[len(MAGIC) + 12:]
    try:
        return AESGCM(_key()).decrypt(nonce, ciphertext, _aad())
    except Exception as exc:
        raise RuntimeError("journal_decryption_failed") from exc


def _headers():
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _url(path: str) -> str:
    root = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    return f"{root}/repos/{_repo()}/{path.lstrip('/')}"


def _request(method: str, path: str, *, json=None, expected=(200,)):
    response = requests.request(
        method, _url(path), headers=_headers(), json=json, timeout=20,
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
        _url("git/refs"),
        headers=_headers(),
        json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        timeout=20,
    )
    if create.status_code not in {201, 422}:
        raise RuntimeError(f"github_state_ref_create_http_{create.status_code}")


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
    return payload["sha"], content


def sync_journal(journal_path):
    path = Path(journal_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError("journal_path_invalid")
    encrypted = encrypt_bytes(path.read_bytes())
    current = _get_state()
    payload = {
        "message": "Persist encrypted ALDI live journal",
        "content": base64.b64encode(encrypted).decode("ascii"),
        "branch": _branch(),
    }
    if current is not None:
        payload["sha"] = current[0]
    state_path = quote(_state_path(), safe="/")
    _request("PUT", f"contents/{state_path}", json=payload, expected=(200, 201))


def restore_journal(journal_path):
    path = Path(journal_path)
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("journal_path_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)

    current = _get_state()
    if current is None:
        Database(str(path))
        path.chmod(0o600)
        sync_journal(path)
        return "initialized"

    plaintext = decrypt_bytes(current[1])
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(plaintext)
    temporary.chmod(0o600)
    os.replace(temporary, path)
    path.chmod(0o600)

    Database(str(path))
    return "restored"
