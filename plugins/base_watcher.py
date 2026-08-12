"""
BaseWatcher-Interface für alle Provider-Plugins.
Definiert das gemeinsame Interface für ALDI und Lidl.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class WatcherResult:
    """Ergebnis eines Watcher-Durchlaufs."""
    provider: str
    username: str
    success: bool
    data_used_mb: float
    data_total_mb: float
    should_recharge: bool
    recharge_triggered: bool
    error_message: Optional[str] = None


class BaseWatcher(ABC):
    """
    Abstrakte Basisklasse für alle Provider-Watcher.
    """

    def __init__(self, username: str, password: str, threshold_mb: float, dry_run: bool = True):
        self.username = username
        self.password = password
        self.threshold_mb = threshold_mb
        self.dry_run = dry_run

    @abstractmethod
    async def check_usage(self) -> Dict[str, float]:
        """
        Prüft das aktuelle Datenvolumen.
        Returns dict mit 'used_mb' und 'total_mb'.
        """
        pass

    @abstractmethod
    async def trigger_recharge(self) -> bool:
        """
        Lst eine Nachbuchung aus.
        Returns True bei Erfolg.
        """
        pass

    async def run(self) -> WatcherResult:
        """
        Fhrt einen kompletten Watcher-Durchlauf durch.
        """
        try:
            usage = await self.check_usage()
            used_mb = usage.get("used_mb", 0)
            total_mb = usage.get("total_mb", 0)
            
            should_recharge = used_mb >= self.threshold_mb
            recharge_triggered = False
            
            if should_recharge:
                if self.dry_run:
                    print(f"DRY RUN: Would trigger recharge for {self.username}")
                else:
                    recharge_triggered = await self.trigger_recharge()
            
            return WatcherResult(
                provider=self.__class__.__name__.replace("Watcher", "").lower(),
                username=self.username,
                success=True,
                data_used_mb=used_mb,
                data_total_mb=total_mb,
                should_recharge=should_recharge,
                recharge_triggered=recharge_triggered
            )
        except Exception as e:
            return WatcherResult(
                provider=self.__class__.__name__.replace("Watcher", "").lower(),
                username=self.username,
                success=False,
                data_used_mb=0,
                data_total_mb=0,
                should_recharge=False,
                recharge_triggered=False,
                error_message=str(e)
            )
