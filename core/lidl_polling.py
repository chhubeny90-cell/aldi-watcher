"""Bounded LIDL polling using the existing consumption-rate estimator."""

import math
from collections import deque
from datetime import datetime, timezone

from core.adaptive_monitor import UsageSample, adaptive_status


class LidlPolling:
    def __init__(self, minimum=30, maximum=300):
        if not 30 <= minimum <= maximum <= 3600:
            raise ValueError("LIDL polling requires 30 <= minimum <= maximum <= 3600")
        self.minimum = minimum
        self.maximum = maximum
        self.samples = deque(maxlen=6)
        self.failures = 0
        self.total_mb = None

    def interval(self, result, threshold_mb=1024, now=None):
        """Failed/uncertain reads never accelerate polling or learn zero usage."""
        values = (result.data_used_mb, result.data_total_mb)
        if (not result.success or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)
                or not 0 <= values[0] <= values[1] or values[1] <= 0):
            self.failures += 1
            self.samples.clear()
            return min(3600, self.maximum * 2 ** min(self.failures - 1, 4))
        self.failures = 0
        if result.recharge_status in {"PENDING", "UNKNOWN", "BLOCKED"}:
            self.samples.clear()
            return self.maximum
        remaining = values[1] - values[0]
        if (self.total_mb != values[1] or result.recharge_triggered
                or (self.samples and remaining > self.samples[-1].remaining_mb)):
            self.samples.clear()
        self.total_mb = values[1]
        self.samples.append(UsageSample(now or datetime.now(timezone.utc), remaining))
        status = adaptive_status(self.samples, refill_threshold_mb=min(1024, threshold_mb))
        delay = status.recommended_interval_seconds
        # Fast first observation near the boundary, even without a burn-rate history.
        if remaining <= 2048:
            delay = min(delay, 60)
        if result.recharge_triggered:
            delay = self.minimum  # Obtain a fresh post-booking volume on the next read.
        return max(self.minimum, min(self.maximum, delay))
