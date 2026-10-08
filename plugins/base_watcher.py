"""Provider-agnostic watcher interface and idempotent recharge orchestration."""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Optional
from dataclasses import dataclass

from core.database import Database, RechargeLockedError


class RechargeUnknownError(RuntimeError):
    """An external booking may have happened; reconciliation is required."""


@dataclass
class WatcherResult:
    provider: str
    username: str
    success: bool
    data_used_mb: float
    data_total_mb: float
    should_recharge: bool
    recharge_triggered: bool
    error_message: Optional[str] = None
    recharge_id: Optional[str] = None
    recharge_status: str = "NOT_TRIGGERED"


class BaseWatcher(ABC):
    def __init__(
        self, username: str, password: str, threshold_mb: float,
        dry_run: bool = True, database: Optional[Database] = None
    ):
        self.username = username
        self.password = password
        self.threshold_mb = threshold_mb
        self.dry_run = dry_run
        self.database = database

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__.replace("Watcher", "").lower()

    @abstractmethod
    async def check_usage(self) -> Dict[str, float]:
        pass

    @abstractmethod
    async def trigger_recharge(self, recharge_id: Optional[str] = None) -> bool:
        """Trigger one recharge. Providers should forward recharge_id when supported."""
        pass

    def should_recharge_for_usage(self, usage: Dict[str, float]) -> bool:
        """Provider decision hook. Default preserves legacy threshold behavior."""
        used_mb = usage.get("used_mb", 0)
        return used_mb >= self.threshold_mb

    async def check_recharge_status(self, recharge_id: str) -> str:
        """Return SUCCESS, FAILED or UNKNOWN. Providers must override when status lookup exists."""
        return "UNKNOWN"

    async def recover_pending(self):
        if self.database is None:
            return []
        resolved = []
        for record in self.database.get_unresolved_recharges(
            self.provider_name, self.username
        ):
            try:
                status = (await self.check_recharge_status(record.recharge_id)).upper()
            except Exception as exc:
                actual = self.database.set_recharge_status(
                    record.recharge_id, "UNKNOWN", type(exc).__name__
                )
                resolved.append((record.recharge_id, actual))
                continue
            if status not in {"SUCCESS", "FAILED", "UNKNOWN"}:
                status = "UNKNOWN"
            actual = self.database.set_recharge_status(record.recharge_id, status)
            resolved.append((record.recharge_id, actual))
        return resolved

    async def _recharge_once(self):
        if self.database is None:
            raise RuntimeError("Live recharge requires persistent Database")
        recharge_id = self.database.begin_recharge(
            self.provider_name, self.username, recent_success_guard_seconds=getattr(self, "recharge_guard_seconds", 30)
        )
        try:
            ok = await self.trigger_recharge(recharge_id)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            status = self.database.set_recharge_status(recharge_id, "UNKNOWN", type(exc).__name__)
            return recharge_id, status, status == "SUCCESS"
        except Exception as exc:
            # The external side effect may have happened before the exception.
            status = self.database.set_recharge_status(recharge_id, "UNKNOWN", type(exc).__name__)
            return recharge_id, status, status == "SUCCESS"

        status = "SUCCESS" if ok else "FAILED"
        status = self.database.set_recharge_status(recharge_id, status)
        return recharge_id, status, status == "SUCCESS"

    async def run(self) -> WatcherResult:
        try:
            if not self.dry_run and self.database is not None:
                await self.recover_pending()

            usage = await self.check_usage()
            used_mb = usage.get("used_mb", 0)
            total_mb = usage.get("total_mb", 0)
            should_recharge = self.should_recharge_for_usage(usage)
            recharge_triggered = False
            recharge_id = None
            recharge_status = "NOT_TRIGGERED"

            if should_recharge:
                if self.dry_run:
                    print(f"DRY RUN: Would trigger recharge for {self.provider_name}")
                else:
                    try:
                        recharge_id, recharge_status, recharge_triggered = (
                            await self._recharge_once()
                        )
                    except RechargeLockedError as exc:
                        recharge_status = "BLOCKED"
                        return WatcherResult(
                            self.provider_name, self.username, True,
                            used_mb, total_mb, True, False, 'recharge_locked',
                            None, recharge_status
                        )

            return WatcherResult(
                self.provider_name, self.username, True,
                used_mb, total_mb, should_recharge, recharge_triggered,
                None, recharge_id, recharge_status
            )
        except Exception as exc:
            return WatcherResult(
                self.provider_name, self.username, False,
                0, 0, False, False, type(exc).__name__
            )
