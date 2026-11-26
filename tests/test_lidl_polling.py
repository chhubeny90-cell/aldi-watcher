from datetime import datetime, timedelta, timezone
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest

from core.lidl_polling import LidlPolling
from plugins.base_watcher import WatcherResult
from plugins.lidl_connect import LidlConnectWatcher
from main import AlDiWatcher


def result(remaining, **kwargs):
    value = WatcherResult('lidlconnect', 'fake', True, 10000 - remaining, 10000, False, False)
    return replace(value, **kwargs)


def test_near_boundary_without_history_is_not_hourly():
    assert LidlPolling().interval(result(1100)) == 60
    assert LidlPolling().interval(result(1023)) == 30
    assert LidlPolling().interval(result(9000)) == 300


def test_consumption_accelerates_and_refill_resets_history():
    polling = LidlPolling()
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    polling.interval(result(3000), now=now)
    assert polling.interval(result(1500), now=now + timedelta(minutes=1)) == 30
    assert polling.interval(result(5000), now=now + timedelta(minutes=2)) == 300
    assert len(polling.samples) == 1


def test_errors_back_off_and_success_recovers():
    polling = LidlPolling()
    failed = result(0, success=False)
    assert [polling.interval(failed) for _ in range(6)] == [300, 600, 1200, 2400, 3600, 3600]
    assert polling.interval(result(1000)) == 30


@pytest.mark.parametrize('status', ['PENDING', 'UNKNOWN', 'BLOCKED'])
def test_uncertain_booking_does_not_create_fast_retry_loop(status):
    assert LidlPolling().interval(result(0, recharge_status=status)) == 300


@pytest.mark.parametrize('used,total', [(float('nan'), 1000), (2000, 1000), (0, 0), (True, 1000)])
def test_invalid_usage_is_not_a_zero_volume_signal(used, total):
    assert LidlPolling().interval(result(0, data_used_mb=used, data_total_mb=total)) == 300


@pytest.mark.parametrize('minimum,maximum', [(0, 300), (15, 300), (300, 30), (30, 3601)])
def test_unsafe_intervals_rejected(minimum, maximum):
    with pytest.raises(ValueError):
        LidlPolling(minimum, maximum)


@pytest.mark.asyncio
async def test_session_survives_success_but_closes_on_error():
    watcher = LidlConnectWatcher('fake', '', 1024, keep_session=True)
    watcher.check_usage = AsyncMock(return_value={'used_mb': 0, 'total_mb': 10000})
    watcher.close = AsyncMock()
    assert (await watcher.run()).success
    assert (await watcher.run()).success
    watcher.close.assert_not_awaited()
    watcher.check_usage.side_effect = RuntimeError('expired')
    assert not (await watcher.run()).success
    watcher.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_session_is_not_retried_or_booked():
    watcher = LidlConnectWatcher('fake', '', 1024, keep_session=True)
    page = MagicMock()
    page.url = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect.html'
    page.goto = AsyncMock()
    page.close = AsyncMock()
    page.locator.return_value.count = AsyncMock(return_value=1)
    page.locator.return_value.is_visible = AsyncMock(return_value=True)
    watcher.page = page
    watcher.trigger_recharge = AsyncMock()
    checked = await watcher.run()
    assert not checked.success
    assert checked.error_message == 'PermissionError'
    page.goto.assert_awaited_once()
    watcher.trigger_recharge.assert_not_awaited()
    assert watcher.page is None


@pytest.mark.asyncio
async def test_close_releases_browser_even_when_page_close_fails():
    watcher = LidlConnectWatcher('fake', '', 1024)
    page, browser, playwright = MagicMock(), MagicMock(), MagicMock()
    page.close = AsyncMock(side_effect=RuntimeError)
    browser.close = AsyncMock()
    playwright.stop = AsyncMock()
    watcher.page, watcher.browser, watcher._playwright = page, browser, playwright
    with pytest.raises(RuntimeError):
        await watcher.close()
    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    assert watcher.page is watcher.browser is watcher._playwright is None


def orchestrator(tmp_path):
    config = SimpleNamespace(db_path=str(tmp_path / 'state.sqlite'),
        aldi_user='', aldi_pass='', lidl_user='', lidl_pass='',
        poll_interval=3600, lidl_adaptive_polling=True,
        lidl_poll_min_seconds=30, lidl_poll_max_seconds=300)
    return AlDiWatcher(config)


@pytest.mark.asyncio
async def test_signal_storm_coalesces_into_same_serial_worker(tmp_path):
    import asyncio
    engine = orchestrator(tmp_path)
    watcher = LidlConnectWatcher('fake', '', 1024, keep_session=True)
    engine._wake_events[watcher.provider_name] = asyncio.Event()
    calls = 0
    async def run(_):
        nonlocal calls
        calls += 1
        for _ in range(50):
            assert engine.request_check(watcher.provider_name)
        if calls == 2:
            engine.running = False
        return result(5000)
    engine._run_watcher = run
    # Simulate passage of minimum spacing without waiting 30 seconds.
    durations = []
    async def wait_for(awaitable, timeout):
        durations.append(timeout)
        awaitable.close()
        raise asyncio.TimeoutError
    with patch('main.asyncio.wait_for', side_effect=wait_for):
        await engine._provider_loop(watcher)
    assert calls == 2
    assert durations == [30]
    assert not engine.request_check('unknown-provider')


@pytest.mark.asyncio
async def test_signal_cannot_bypass_failure_backoff(tmp_path):
    import asyncio
    engine = orchestrator(tmp_path)
    watcher = LidlConnectWatcher('fake', '', 1024)
    engine._wake_events[watcher.provider_name] = asyncio.Event()
    engine._run_watcher = AsyncMock(return_value=result(0, success=False))
    durations = []
    async def wait_for(awaitable, timeout):
        durations.append(timeout)
        engine.request_check(watcher.provider_name)
        engine.running = False
        awaitable.close()
        raise asyncio.TimeoutError
    with patch('main.asyncio.wait_for', side_effect=wait_for):
        await engine._provider_loop(watcher)
    assert durations == [300]


@pytest.mark.asyncio
async def test_existing_session_reads_without_another_login():
    watcher = LidlConnectWatcher('fake', '', 1024, keep_session=True, refill_selectors={})
    page = MagicMock()
    page.url = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect.html'
    page.goto = AsyncMock()
    page.text_content = AsyncMock(return_value='100 MB von 10000 MB')
    page.locator.return_value.count = AsyncMock(return_value=0)
    watcher.page = page
    watcher._init_browser = AsyncMock()
    watcher._pw_login = AsyncMock()
    await watcher.check_usage()
    await watcher.check_usage()
    watcher._init_browser.assert_not_awaited()
    watcher._pw_login.assert_not_awaited()
    assert page.goto.await_count == 2


@pytest.mark.asyncio
async def test_other_provider_keeps_its_own_interval(tmp_path):
    import asyncio
    engine = orchestrator(tmp_path)
    watcher = SimpleNamespace(provider_name='other')
    engine._wake_events['other'] = asyncio.Event()
    engine._run_watcher = AsyncMock(return_value=replace(result(1100), provider='other'))
    durations = []
    async def wait_for(awaitable, timeout):
        durations.append(timeout)
        engine.running = False
        awaitable.close()
        raise asyncio.TimeoutError
    with patch('main.asyncio.wait_for', side_effect=wait_for):
        await engine._provider_loop(watcher)
    assert durations == [3600]
