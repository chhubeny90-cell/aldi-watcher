import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.database import Database
from plugins.lidl_connect import LidlConnectWatcher


def eligible_watcher(tmp_path, use_api):
    db = Database(str(tmp_path / "db.sqlite"))
    watcher = LidlConnectWatcher("fake", "fake", 500, dry_run=False, use_api=use_api, database=db)
    watcher.check_usage = AsyncMock(return_value={"used_mb": 999, "total_mb": 1000,
                                                "refill_eligible": True, "refill_type": "FREE_UNLIMITED"})
    return watcher, db


def test_api_timeout_never_falls_back_or_rebooks(tmp_path):
    watcher, db = eligible_watcher(tmp_path, True)
    watcher._api_trigger_recharge = AsyncMock(side_effect=asyncio.TimeoutError())
    watcher._pw_trigger_recharge = AsyncMock()
    first = asyncio.run(watcher.run())
    assert first.recharge_status == "UNKNOWN"
    second = asyncio.run(watcher.run())
    assert second.recharge_status == "BLOCKED"
    watcher._api_trigger_recharge.assert_awaited_once()
    watcher._pw_trigger_recharge.assert_not_awaited()
    assert db.get_unresolved_recharges()[0].status == "UNKNOWN"


def test_browser_timeout_after_click_preserves_unknown_and_single_click(tmp_path):
    from tests.test_lidl_refill_availability import browser_watcher, ELIGIBLE
    watcher, db, page, offer, button, success = browser_watcher(tmp_path)
    watcher.check_usage = AsyncMock(return_value={"used_mb": 999, "total_mb": 1000, **ELIGIBLE})
    success.wait_for.side_effect = asyncio.TimeoutError()
    result = asyncio.run(watcher.run())
    assert result.recharge_status == "UNKNOWN"
    assert not result.recharge_triggered
    button.click.assert_awaited_once()
    assert db.get_unresolved_recharges()[0].status == "UNKNOWN"
    assert asyncio.run(watcher.run()).recharge_status == "BLOCKED"
    button.click.assert_awaited_once()
