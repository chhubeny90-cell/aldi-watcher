"""
Haupt-Orchestrator für aldi-watcher.
Sequenzielle Hauptschleife mit strikter Fehler-Isolierung.
"""

import asyncio
import signal
from typing import List
from datetime import datetime

from core.database import Database, UsageLog
from core.config import Config
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
        
        # Watcher initialisieren
        self.watchers: List = []
        
        if config.aldi_user and config.aldi_pass:
            self.watchers.append(
                AldiTalkWatcher(
                    config.aldi_user,
                    config.aldi_pass,
                    config.threshold_aldi_mb,
                    config.dry_run
                )
            )
        
        if config.lidl_user and config.lidl_pass:
            self.watchers.append(
                LidlConnectWatcher(
                    config.lidl_user,
                    config.lidl_pass,
                    config.threshold_lidl_mb,
                    config.dry_run
                )
            )

    def _setup_signal_handlers(self):
        """Setup für Graceful Shutdown (SIGINT/SIGTERM)."""
        def signal_handler(sig, frame):
            print(f"\nReceived signal {sig}, shutting down...")
            self.running = False
        
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
            threshold_mb=self.config.threshold_aldi_mb if result.provider == "aldi" else self.config.threshold_lidl_mb,
            should_recharge=result.should_recharge,
            recharge_triggered=result.recharge_triggered,
            error_message=result.error_message,
            created_at=datetime.now()
        )
        
        self.db.log_usage(log)
        
        # Logging
        status = "OK" if result.success else "ERROR"
        print(f"[{status}] {result.provider.upper()} | {result.username} | "
              f"{result.data_used_mb:.0f}/{result.data_total_mb:.0f} MB | "
              f"Recharge: {result.recharge_triggered}")
        
        if result.error_message:
            print(f"  Error: {result.error_message}")

    async def run_once(self):
        """
        Fhrt einen einzelnen Durchlauf aller Watcher durch.
        Jeder Watcher in eigenem try-except für Fehler-Isolierung.
        """
        for watcher in self.watchers:
            try:
                # Watcher ausfhren
                result = await watcher.run()
                await self._process_watcher_result(result)
                
            except Exception as e:
                # Fehler-Isolierung: Ein Absturz blockiert nicht andere Watcher
                error_msg = f"Watcher crashed: {type(watcher).__name__}: {e}"
                print(f"[ERROR] {error_msg}")
                
                # ERROR-Eintrag in DB
                self.db.log_error(
                    provider=watcher.__class__.__name__.replace("Watcher", "").lower(),
                    username=watcher.username,
                    error_message=error_msg
                )

    async def run_loop(self):
        """
        Hauptschleife mit Polling-Interval.
        """
        self._setup_signal_handlers()
        
        print(f"Starting aldi-watcher (DRY_RUN={self.config.dry_run})")
        print(f"Poll interval: {self.config.poll_interval}s")
        print(f"Watchers: {[w.__class__.__name__ for w in self.watchers]}")
        print("-" * 50)
        
        while self.running:
            await self.run_once()
            
            if self.running:
                await asyncio.sleep(self.config.poll_interval)

    async def shutdown(self):
        """Graceful Shutdown aller Watcher."""
        for watcher in self.watchers:
            try:
                if hasattr(watcher, 'close'):
                    await watcher.close()
            except Exception as e:
                print(f"Error closing {watcher.__class__.__name__}: {e}")


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
