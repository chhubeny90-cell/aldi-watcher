"""
Unit-Tests für AldiTalkWatcher.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from plugins.aldi_talk import AldiTalkWatcher
from core.database import Database
import asyncio


def test_unverified_aldi_recharge_blocks_without_sending_request(tmp_path):
    db = Database(str(tmp_path / 'db.sqlite'))
    watcher = AldiTalkWatcher('fake', 'fake', 500, dry_run=False, database=db)
    watcher.check_usage = AsyncMock(return_value={
        'used_mb': 999, 'total_mb': 1000,
        'refill_eligible': True, 'refill_type': 'FREE_UNLIMITED'})
    watcher.login = AsyncMock(return_value='fake-cookie')
    session = MagicMock()
    watcher._get_session = AsyncMock(return_value=session)
    assert asyncio.run(watcher.run()).recharge_status == 'UNKNOWN'
    assert asyncio.run(watcher.run()).recharge_status == 'BLOCKED'
    watcher._get_session.assert_not_called()
    watcher.login.assert_not_called()
    session.post.assert_not_called()
    assert db.get_unresolved_recharges()[0].status == 'UNKNOWN'


@pytest.mark.asyncio
@pytest.mark.parametrize('dry_run', [True, False])
async def test_direct_aldi_recharge_is_disabled_before_network_access(dry_run):
    watcher = AldiTalkWatcher('sensitive-account', 'sensitive-secret', 500, dry_run=dry_run)
    watcher._get_session = AsyncMock()
    watcher.login = AsyncMock()
    with pytest.raises(NotImplementedError, match='authorized and verified'):
        await watcher.trigger_recharge(recharge_id='fixture-id')
    watcher._get_session.assert_not_called()
    watcher.login.assert_not_called()


class TestAldiTalkWatcher:
    """Tests für ALDI Talk Watcher."""

    @pytest.fixture
    def watcher(self):
        """Erstellt Test-Watcher mit DRY_RUN."""
        return AldiTalkWatcher(
            username="test@example.com",
            password="testpass",
            threshold_mb=500,
            dry_run=True
        )

    def test_init(self, watcher):
        """Testet Initialisierung."""
        assert watcher.username == "test@example.com"
        assert watcher.threshold_mb == 500

    @pytest.mark.asyncio
    async def test_check_usage_success(self, watcher):
        """Testet erfolgreiche Usage-Prfung."""
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
        """Testet DRY_RUN-Modus."""
        with patch.object(watcher, 'check_usage', new=AsyncMock(return_value={"used_mb": 600, "total_mb": 1000})):
            with patch.object(watcher, 'trigger_recharge', new=AsyncMock()) as mock_recharge:
                result = await watcher.run()
                
                assert result.success is True
                assert result.should_recharge is False
                assert result.recharge_triggered is False  # DRY_RUN!
                mock_recharge.assert_not_called()

    @pytest.mark.asyncio
    async def test_free_unlimited_refill_requires_verified_eligibility(self, watcher):
        usage = {
            "used_mb": 9999,
            "total_mb": 10000,
            "refill_eligible": True,
            "refill_type": "FREE_UNLIMITED",
        }
        with patch.object(watcher, 'check_usage', new=AsyncMock(return_value=usage)):
            result = await watcher.run()
        assert result.should_recharge is True
        assert result.recharge_triggered is False

    @pytest.mark.asyncio
    async def test_paid_or_unverified_refill_is_blocked(self, watcher):
        for usage in (
            {"used_mb": 9999, "total_mb": 10000},
            {"used_mb": 9999, "total_mb": 10000, "refill_eligible": True, "refill_type": "PAID"},
        ):
            with patch.object(watcher, 'check_usage', new=AsyncMock(return_value=usage)):
                result = await watcher.run()
            assert result.should_recharge is False
