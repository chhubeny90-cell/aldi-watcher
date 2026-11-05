"""Lidl API fail-closed regression tests; provider network is never contacted."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from plugins.lidl_connect import LidlConnectWatcher


def make_watcher(**overrides):
    config = dict(username="example", password="test", threshold_mb=500, dry_run=True, use_api=False)
    config.update(overrides)
    return LidlConnectWatcher(**config)


def test_unverified_api_setting_fails_during_construction():
    with pytest.raises(ValueError, match="LIDL_USE_API must be false"):
        make_watcher(use_api=True)


@pytest.mark.asyncio
async def test_explicit_api_methods_are_closed():
    watcher = make_watcher()
    with pytest.raises(RuntimeError, match="unverified_lidl_api_disabled"):
        await watcher._api_login()
    with pytest.raises(RuntimeError, match="unverified_lidl_api_disabled"):
        await watcher._api_check_usage()
    assert await watcher._api_trigger_recharge() is False


@pytest.mark.asyncio
async def test_usage_does_not_fall_back_to_guessed_api_even_if_flag_is_mutated():
    watcher = make_watcher()
    watcher.use_api = True  # defend against legacy runtime mutation
    watcher._pw_check_usage = AsyncMock(return_value={"used_mb": 0, "total_mb": 1024})
    watcher._api_check_usage = AsyncMock(side_effect=AssertionError("legacy API invoked"))
    usage = await watcher.check_usage()
    assert usage["total_mb"] == 1024
    watcher._pw_check_usage.assert_awaited_once()
    watcher._api_check_usage.assert_not_awaited()


def test_guessed_lidl_endpoint_literals_are_absent():
    source = (Path(__file__).resolve().parents[1] / "plugins" / "lidl_connect.py").read_text(encoding="utf-8")
    assert "/api/authenticate" not in source
    assert "/api/consumption" not in source
    assert "/api/tariff-option/book" not in source
    assert "session.post(" not in source
