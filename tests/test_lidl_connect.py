"""
Unit-Tests für LidlConnectWatcher.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from plugins.lidl_connect import LidlConnectWatcher


class TestLidlConnectWatcher:
    """Tests für Lidl Connect Watcher."""

    @pytest.fixture
    def watcher(self):
        """Erstellt Test-Watcher mit DRY_RUN."""
        return LidlConnectWatcher(
            username="test@example.com",
            password="testpass",
            threshold_mb=500,
            dry_run=True,
            use_api=False
        )

    def test_init(self, watcher):
        """Testet Initialisierung."""
        assert watcher.username == "test@example.com"
        assert watcher.password == "testpass"
        assert watcher.threshold_mb == 500
        assert watcher.dry_run is True

    @pytest.mark.asyncio
    async def test_check_usage_success(self, watcher):
        """Testet erfolgreiche Usage-Prfung."""
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.text_content = AsyncMock(return_value="1234 MB von 5000 MB")
        watcher.page = mock_page

        result = await watcher.check_usage()

        assert result["used_mb"] == 1234
        assert result["total_mb"] == 5000

    @pytest.mark.asyncio
    async def test_check_usage_parse_error(self, watcher):
        """Testet Parsing-Fehler."""
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.text_content = AsyncMock(return_value="Invalid format")
        watcher.page = mock_page

        with pytest.raises(Exception, match="Could not parse"):
            await watcher.check_usage()

    @pytest.mark.asyncio
    async def test_direct_dry_run_never_clicks(self, watcher):
        mock_page = MagicMock()
        mock_page.click = AsyncMock()
        watcher.page = mock_page
        assert await watcher.trigger_recharge() is False
        mock_page.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, watcher):
        """Testet exponentiellen Backoff."""
        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Timeout")
            return "success"

        result = await watcher._exponential_backoff(failing_func, max_retries=5, base_delay=0.01)

        assert result == "success"
        assert call_count == 3

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
    async def test_run_with_error(self, watcher):
        """Testet Fehlerbehandlung."""
        with patch.object(watcher, 'check_usage', new=AsyncMock(side_effect=Exception("Network error"))):
            result = await watcher.run()

            assert result.success is False
            assert result.error_message == "Network error"

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
