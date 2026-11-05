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


def test_unverified_api_mode_is_rejected_before_any_booking(tmp_path):
    with pytest.raises(ValueError, match="LIDL_USE_API must be false"):
        eligible_watcher(tmp_path, True)


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
