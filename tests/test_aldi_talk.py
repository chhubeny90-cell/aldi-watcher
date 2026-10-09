"""Unit tests for AldiTalkWatcher."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.database import Database
from plugins.aldi_talk import AldiTalkWatcher
from plugins.base_watcher import RechargeUnknownError


def test_uncertain_aldi_post_response_blocks_rebooking(tmp_path):
    db = Database(str(tmp_path / 'db.sqlite'))
    watcher = AldiTalkWatcher('fake', 'fake', 500, dry_run=False, database=db)
    watcher.check_usage = AsyncMock(return_value={
        'used_mb': 999, 'total_mb': 1000,
        'refill_eligible': True, 'refill_type': 'FREE_ONE_GB'})
    # Simulate an uncertain provider response independently of the disabled
    # legacy endpoint. Production booking remains covered by the no-network guard.
    watcher.trigger_recharge = AsyncMock(side_effect=RechargeUnknownError('unconfirmed'))
    assert asyncio.run(watcher.run()).recharge_status == 'UNKNOWN'
    assert asyncio.run(watcher.run()).recharge_status == 'BLOCKED'
    watcher.trigger_recharge.assert_awaited_once()
    assert db.get_unresolved_recharges()[0].status == 'UNKNOWN'


class TestAldiTalkWatcher:
    @pytest.fixture
    def watcher(self):
        return AldiTalkWatcher(
            username="test@example.com",
            password="testpass",
            threshold_mb=500,
            dry_run=True
        )

    def test_init(self, watcher):
        assert watcher.username == "test@example.com"
        assert watcher.threshold_mb == 500

    @pytest.mark.asyncio
    async def test_check_usage_success(self, watcher):
        mock_response = AsyncMock()
        mock_response.text = AsyncMock(return_value="1234 MB von 5000 MB")
        response_cm = MagicMock()
        response_cm.__aenter__ = AsyncMock(return_value=mock_response)
        response_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session = MagicMock()
        mock_session.get.return_value = response_cm

        with patch.object(watcher, '_get_session', new=AsyncMock(return_value=mock_session)):
            with patch.object(watcher, 'login', new=AsyncMock(return_value="session-cookie")):
                result = await watcher.check_usage()
            assert result["used_mb"] == 1234
            assert result["total_mb"] == 5000

    @pytest.mark.asyncio
    async def test_run_dry_run(self, watcher):
        with patch.object(watcher, 'check_usage', new=AsyncMock(return_value={"used_mb": 600, "total_mb": 1000})):
            with patch.object(watcher, 'trigger_recharge', new=AsyncMock()) as mock_recharge:
                result = await watcher.run()
                assert result.success is True
                assert result.should_recharge is False
                assert result.recharge_triggered is False
                mock_recharge.assert_not_called()

    @pytest.mark.asyncio
    async def test_free_one_gb_refill_requires_verified_eligibility(self, watcher):
        usage = {
            "used_mb": 9999,
            "total_mb": 10000,
            "refill_eligible": True,
            "refill_type": "FREE_ONE_GB",
        }
        with patch.object(watcher, 'check_usage', new=AsyncMock(return_value=usage)):
            result = await watcher.run()
        assert result.should_recharge is True
        assert result.recharge_triggered is False

    @pytest.mark.asyncio
    async def test_old_or_unverified_refill_type_is_blocked(self, watcher):
        for usage in (
            {"used_mb": 9999, "total_mb": 10000},
            {"used_mb": 9999, "total_mb": 10000, "refill_eligible": True, "refill_type": "PAID"},
            {"used_mb": 9999, "total_mb": 10000, "refill_eligible": True, "refill_type": "FREE_UNLIMITED"},
        ):
            with patch.object(watcher, 'check_usage', new=AsyncMock(return_value=usage)):
                result = await watcher.run()
            assert result.should_recharge is False
