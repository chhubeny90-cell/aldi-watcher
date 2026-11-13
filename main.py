"""
Haupt-Orchestrator für aldi-watcher.
Ein serieller Worker je Anbieter mit unabhängigen Prüfintervallen.
"""

import asyncio
import signal
from typing import List
from datetime import datetime

from core.database import Database, UsageLog
from core.config import Config
from core.lidl_polling import LidlPolling
from plugins.base_watcher import WatcherResult
from plugins.aldi_talk import AldiTalkWatcher
from plugins.lidl_connect import LidlConnectWatcher


class AlDiWatcher:
    """
    Haupt-Orchestrator für ALDI Talk und Lidl Connect.
    """

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(config.db_path)
        self.running = True
        self._stop = asyncio.Event()
        self._wake_events = {}
        self._lidl_polling = LidlPolling(config.lidl_poll_min_seconds, config.lidl_poll_max_seconds)
        
        # Watcher initialisieren
        self.watchers: List = []
        
        if config.aldi_user and config.aldi_pass:
            self.watchers.append(
                AldiTalkWatcher(
                    config.aldi_user,
                    config.aldi_pass,
                    config.threshold_aldi_mb,
                    config.dry_run,
                    self.db
                )
            )
        
        if config.lidl_user and config.lidl_pass:
            self.watchers.append(
                LidlConnectWatcher(
                    config.lidl_user,
                    config.lidl_pass,
                    config.threshold_lidl_mb,
                    config.dry_run,
                    use_api=config.lidl_use_api,
                    database=self.db,
                    refill_selectors=config.lidl_refill_selectors,
                    refill_mode=config.lidl_refill_mode,
                    keep_session=True
                )
            )

    def _setup_signal_handlers(self):
        """Setup für Graceful Shutdown (SIGINT/SIGTERM)."""
        def signal_handler(sig, frame):
            print(f"\nReceived signal {sig}, shutting down...")
            self.running = False
            self._stop.set()
            for event in self._wake_events.values():
                event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def _process_watcher_result(self, result: WatcherResult):
        """
        Verarbeitet Watcher-Ergebnis und loggt in DB.
        """
        log = UsageLog(
            id=None,
            provider=result.provider,
            username=result.username,
            data_used_mb=result.data_used_mb,
            data_total_mb=result.data_total_mb,
            threshold_mb=self.config.threshold_aldi_mb if result.provider in {"aldi", "alditalk"} else self.config.threshold_lidl_mb,
            should_recharge=result.should_recharge,
            recharge_triggered=result.recharge_triggered,
            error_message=result.error_message,
            created_at=datetime.now()
        )
        
        self.db.log_usage(log)
        
        # Logging
        status = "OK" if result.success else "ERROR"
        print(f"[{status}] {result.provider.upper()} | "
              f"{result.data_used_mb:.0f}/{result.data_total_mb:.0f} MB | "
              f"Recharge: {result.recharge_triggered}")
        
        if result.error_message:
            print(f"  Error: {result.error_message}")

    async def _run_watcher(self, watcher):
        try:
            result = await watcher.run()
            await self._process_watcher_result(result)
            return result
        except Exception as exc:
            self.db.log_error(
                provider=watcher.provider_name, username=watcher.username,
                error_message=type(exc).__name__
            )
            return None

    def request_check(self, provider):
        """Coalesce trusted in-process signals; never bypass the booking journal.

        An SMS/mail receiver must validate sender and SIM before calling this.
        This is an adapter hook, not a configured SMS receiver or webhook.
        """
        event = self._wake_events.get(provider)
        if event is None:
            return False
        event.set()
        return True

    async def _provider_loop(self, watcher):
        event = self._wake_events[watcher.provider_name]
        failures = 0
        while self.running:
            event.clear()
            result = await self._run_watcher(watcher)
            if result is None:
                failures += 1
                delay = min(3600, self.config.poll_interval * 2 ** min(failures - 1, 4))
            elif isinstance(watcher, LidlConnectWatcher) and self.config.lidl_adaptive_polling:
                delay = self._lidl_polling.interval(result, watcher.threshold_mb)
                failures = 0 if result.success else failures + 1
            else:
                delay = self.config.poll_interval
                failures = 0 if result.success else failures + 1
            if not self.running:
                break
            # Signals shorten healthy idle waits, but cannot defeat minimum spacing
            # or the error backoff. Each provider has exactly one serial worker.
            minimum = self.config.lidl_poll_min_seconds if isinstance(watcher, LidlConnectWatcher) else self.config.poll_interval
            limited = failures or (result is not None and result.recharge_status in {"PENDING", "UNKNOWN", "BLOCKED"})
            if isinstance(watcher, LidlConnectWatcher) and self.config.lidl_adaptive_polling:
                limited = limited or self._lidl_polling.failures
            floor = delay if limited else min(minimum, delay)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=floor)
            except asyncio.TimeoutError:
                pass
            if not self.running:
                break
            if delay > floor and not event.is_set():
                try:
                    await asyncio.wait_for(event.wait(), timeout=delay - floor)
                except asyncio.TimeoutError:
                    pass

    async def run_once(self):
        """
        Fhrt einen einzelnen Durchlauf aller Watcher durch.
        Jeder Watcher in eigenem try-except für Fehler-Isolierung.
        """
        for watcher in self.watchers:
            await self._run_watcher(watcher)

    async def run_loop(self):
        """
        Hauptschleife mit Polling-Interval.
        """
        self._setup_signal_handlers()
        
        print(f"Starting aldi-watcher (DRY_RUN={self.config.dry_run})")
        print(f"Poll interval: {self.config.poll_interval}s")
        print(f"Watchers: {[w.__class__.__name__ for w in self.watchers]}")
        print("-" * 50)
        
        self._wake_events = {watcher.provider_name: asyncio.Event() for watcher in self.watchers}
        tasks = [asyncio.create_task(self._provider_loop(watcher)) for watcher in self.watchers]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self):
        """Graceful Shutdown aller Watcher."""
        for watcher in self.watchers:
            try:
                if hasattr(watcher, 'close'):
                    await watcher.close()
            except Exception as e:
                print(f"Error closing {watcher.__class__.__name__}: {type(e).__name__}")


async def main():
    """
    Entry Point für aldi-watcher.
    """
    config = Config()
    
    if not config.validate():
        print("Configuration validation failed. Check .env file.")
        return
    
    orchestrator = AlDiWatcher(config)
    
    try:
        await orchestrator.run_loop()
    finally:
        await orchestrator.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
