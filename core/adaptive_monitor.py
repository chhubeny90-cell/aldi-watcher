"""Adaptive polling decisions derived from recent high-speed volume samples."""

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable, Optional


@dataclass(frozen=True)
class UsageSample:
    timestamp: datetime
    remaining_mb: float


@dataclass(frozen=True)
class AdaptiveStatus:
    remaining_mb: float
    burn_rate_mb_per_min: float
    eta_to_refill_min: Optional[float]
    recommended_interval_seconds: int
    pressure: str


def _positive_burn_rates(samples: list[UsageSample]) -> list[float]:
    rates: list[float] = []
    for older, newer in zip(samples, samples[1:]):
        elapsed_min = (newer.timestamp - older.timestamp).total_seconds() / 60.0
        if elapsed_min <= 0:
            continue
        consumed = older.remaining_mb - newer.remaining_mb
        # A negative delta normally means a refill/reset happened. Treat it as a
        # new cycle instead of learning a bogus negative consumption rate.
        if consumed <= 0:
            continue
        rates.append(consumed / elapsed_min)
    return rates


def adaptive_status(samples: Iterable[UsageSample], refill_threshold_mb: float = 1000.0) -> AdaptiveStatus:
    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    if not ordered:
        raise ValueError("at least one usage sample is required")

    remaining = max(0.0, float(ordered[-1].remaining_mb))
    recent_rates = _positive_burn_rates(ordered[-6:])
    burn_rate = median(recent_rates) if recent_rates else 0.0

    if remaining <= refill_threshold_mb:
        eta = 0.0
        interval = 15
        pressure = "refill_zone"
    elif burn_rate <= 0:
        eta = None
        interval = 300
        pressure = "idle"
    else:
        eta = (remaining - refill_threshold_mb) / burn_rate
        if eta <= 3:
            interval = 15
            pressure = "critical"
        elif eta <= 10:
            interval = 30
            pressure = "high"
        elif eta <= 30:
            interval = 60
            pressure = "medium"
        elif eta <= 120:
            interval = 120
            pressure = "low"
        else:
            interval = 300
            pressure = "idle"

    return AdaptiveStatus(
        remaining_mb=round(remaining, 3),
        burn_rate_mb_per_min=round(burn_rate, 3),
        eta_to_refill_min=None if eta is None else round(max(0.0, eta), 3),
        recommended_interval_seconds=interval,
        pressure=pressure,
    )
