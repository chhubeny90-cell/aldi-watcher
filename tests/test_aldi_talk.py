"""
Unit-Tests für AldiTalkWatcher.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from plugins.aldi_talk import AldiTalkWatcher


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
        with patch.object(watcher, '_get_session', new=AsyncMock()) as mock_session:
            mock_session_instance = MagicMock()
            mock_session.return_value = mock_session_instance
            
            # Mock response
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value="1234 MB von 5000 MB")
            
            mock_session_instance.get = AsyncMock(return_value=mock_response)
            
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
                assert result.should_recharge is True
                assert result.recharge_triggered is False  # DRY_RUN!
                mock_recharge.assert_not_called()
