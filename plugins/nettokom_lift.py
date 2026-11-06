"""Separate, deliberately disabled NettoKOM LIFT provider integration slot."""
from .base_watcher import BaseWatcher
from core.nettokom_lift import LiftAssessment, LiftObservation, assess_lift


class NettoKomLiftWatcher(BaseWatcher):
    """Offline-only until explicit provider permission and live contracts exist."""

    @property
    def provider_name(self) -> str:
        return "nettokom_lift"

    @staticmethod
    def assess_offline(observation: LiftObservation) -> LiftAssessment:
        return assess_lift(observation)

    def should_recharge_for_usage(self, usage):
        return False

    async def check_usage(self):
        raise RuntimeError("nettokom_live_usage_unavailable")

    async def trigger_recharge(self, recharge_id=None):
        raise RuntimeError("nettokom_live_booking_disabled")
