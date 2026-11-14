"""Offline tests for encrypted Playwright state and UI helper boundaries."""

import asyncio
import os
import random
from datetime import timedelta
from unittest.mock import AsyncMock

from cryptography.fernet import Fernet
import pytest

from refill_v2.humanizer import (
    create_context, pause, retry_read_only, scroll_into_view, type_interactively,
)
from refill_v2.session_vault import SessionVault


@pytest.fixture
def vault(tmp_path):
    return SessionVault(tmp_path / "secret", Fernet.generate_key())


@pytest.mark.asyncio
async def test_session_is_encrypted_and_bound_to_account(vault):
    auth_state = {
        "cookies": [{"name": "session", "value": "token-only-in-encrypted-data",
                     "domain": "example.invalid", "path": "/"}],
        "origins": [],
    }
    context = AsyncMock()
    context.storage_state.return_value = auth_state
    await vault.save_session("aldi_primary", context)
    context.storage_state.assert_awaited_once_with(indexed_db=True)
    raw = (vault.directory / "aldi_primary.session.enc").read_bytes()
    assert b"token-only-in-encrypted-data" not in raw
    assert vault.load_session("aldi_primary") == auth_state
    assert vault.load_session("lidl_other") is None
    if os.name == "posix":
        assert (vault.directory / "aldi_primary.session.enc").stat().st_mode & 0o077 == 0


def test_credentials_are_encrypted_and_account_bound(vault):
    vault.save_credentials("aldi_primary", "test_login", "test_password")
    raw = (vault.directory / "aldi_primary.credentials.enc").read_bytes()
    assert b"test_login" not in raw and b"test_password" not in raw
    assert vault.load_credentials("aldi_primary") == ("test_login", "test_password")
    assert vault.load_credentials("lidl_other") is None
    with pytest.raises(ValueError):
        vault.save_credentials("unsafe/account", "x", "y")


def test_wrong_key_fails_closed(vault):
    vault.save_credentials("aldi_primary", "user", "password")
    other = SessionVault(vault.directory, Fernet.generate_key())
    with pytest.raises(ValueError, match="could not be validated"):
        other.load_credentials("aldi_primary")


def test_key_not_auto_generated_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("REFILL_SESSION_FERNET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="missing"):
        SessionVault.from_environment(tmp_path / "secret")


@pytest.mark.asyncio
async def test_interaction_helpers_have_no_refill_click():
    locator = AsyncMock()
    locator.count.return_value = 1
    await scroll_into_view(locator)
    await type_interactively(locator, "abc", rng=random.Random(1))
    locator.scroll_into_view_if_needed.assert_awaited_once_with(timeout=10_000)
    assert locator.press_sequentially.await_count == 3
    assert all(50 <= item.kwargs["delay"] <= 140
               for item in locator.press_sequentially.await_args_list)
    assert not locator.click.await_count


@pytest.mark.asyncio
async def test_retry_readonly_runs_at_most_three_attempts(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr("refill_v2.humanizer.asyncio.sleep",
                        AsyncMock(side_effect=lambda value: sleeps.append(value)))

    async def failing():
        calls.append(1)
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        await retry_read_only(failing, retries=2, rng=random.Random(1))
    assert len(calls) == 3
    assert len(sleeps) == 2

    with pytest.raises(ValueError):
        await retry_read_only(failing, retries=3)


@pytest.mark.asyncio
async def test_non_timeout_errors_are_never_retried():
    action = AsyncMock(side_effect=RuntimeError("429 or authentication"))
    with pytest.raises(RuntimeError):
        await retry_read_only(action)
    action.assert_awaited_once()


@pytest.mark.asyncio
async def test_consistent_context_options_without_user_agent_spoofing():
    browser = AsyncMock()
    browser.new_context.return_value = object()
    await create_context(browser, storage_state={"cookies": [], "origins": []})
    opts = browser.new_context.await_args.kwargs
    assert opts["storage_state"]["cookies"] == []
    assert opts["locale"] == "de-DE"
    assert "user_agent" not in opts


@pytest.mark.asyncio
async def test_pause_is_bounded(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("refill_v2.humanizer.asyncio.sleep", sleep)
    await pause(1.8, 4.5, rng=random.Random(1))
    assert 1.8 <= sleep.await_args.args[0] <= 4.5


def test_expired_session_returns_none(vault):
    vault._write(vault._file("aldi_primary", "session"), {
        "version": 1, "account_id": "aldi_primary",
        "saved_at": "2001-01-01T00:00:00+00:00",
        "storage_state": {"cookies": [], "origins": []},
    })
    assert vault.load_session("aldi_primary") is None
