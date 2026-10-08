"""Regression tests: unverified ALDI booking must never contact a provider."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from plugins.aldi_talk import AldiTalkWatcher


def test_aldi_unverified_booking_does_not_send_request():
    watcher = AldiTalkWatcher("test", "test", 500, dry_run=False)
    watcher._get_session = AsyncMock(side_effect=AssertionError("network request attempted"))
    with pytest.raises(RuntimeError, match="no verified free 1-GB flow"):
        asyncio.run(watcher.trigger_recharge())
    watcher._get_session.assert_not_called()
