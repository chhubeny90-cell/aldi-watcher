"""Adaptive, read-only ALDI high-speed volume monitor.

Designed for the active window after a consumption trigger (for example the
80-percent email). It keeps one authenticated browser session open, samples
remaining high-speed volume, learns the current burn rate and automatically
shortens the next check interval. It never books or clicks a refill control.
"""

import json
import os
import time
from datetime import datetime, timezone

from core.adaptive_monitor import UsageSample, adaptive_status
import watcher


MAX_RUNTIME_SECONDS = max(60, int(os.getenv("ALDI_ACTIVE_MONITOR_MAX_SECONDS", "3600")))
INITIAL_INTERVAL_SECONDS = max(15, int(os.getenv("ALDI_ACTIVE_MONITOR_INITIAL_SECONDS", "60")))
REPORT_PATH = os.getenv("ALDI_ACTIVE_MONITOR_REPORT", "aldi-active-monitor.json")


def now_utc():
    return datetime.now(timezone.utc)


def main():
    report = {
        "started_at": now_utc().isoformat(),
        "finished_at": None,
        "outcome": "unknown",
        "booking_executed": False,
        "samples": [],
    }

    if not watcher.configure_credentials("ALDI"):
        report["outcome"] = "credentials_unavailable"
        _write(report)
        return 3

    driver = None
    started = time.monotonic()
    learned_samples = []
    next_interval = INITIAL_INTERVAL_SECONDS

    try:
        driver = watcher.build_driver()
        if not watcher.aldi_login(driver):
            report["outcome"] = "auth_failed"
            return 2

        while time.monotonic() - started < MAX_RUNTIME_SECONDS:
            checked_at = now_utc()
            status = watcher.aldi_read_status(driver)
            remaining_gb = status.get("inland_frei_gb")
            if isinstance(remaining_gb, bool) or not isinstance(remaining_gb, (int, float)) or remaining_gb < 0:
                report["outcome"] = "usage_invalid"
                return 2

            learned_samples.append(UsageSample(checked_at, float(remaining_gb) * 1000.0))
            learned = adaptive_status(learned_samples, refill_threshold_mb=1000.0)
            if len(learned_samples) == 1 and learned.remaining_mb > 1000.0:
                next_interval = INITIAL_INTERVAL_SECONDS
            else:
                next_interval = learned.recommended_interval_seconds

            public_sample = {
                "checked_at": checked_at.isoformat(),
                "remaining_gb": round(float(remaining_gb), 3),
                "burn_rate_mb_per_min": learned.burn_rate_mb_per_min,
                "eta_to_refill_min": learned.eta_to_refill_min,
                "next_check_seconds": next_interval,
                "pressure": learned.pressure,
            }
            report["samples"].append(public_sample)
            print(json.dumps(public_sample, ensure_ascii=False), flush=True)
            _write(report)

            if learned.remaining_mb <= 1000.0:
                report["outcome"] = "refill_zone_reached"
                return 0

            remaining_runtime = MAX_RUNTIME_SECONDS - (time.monotonic() - started)
            if remaining_runtime <= 0:
                break
            time.sleep(min(next_interval, remaining_runtime))

        report["outcome"] = "monitor_window_finished"
        return 0
    except Exception as exc:
        report["outcome"] = "error"
        report["exception_type"] = type(exc).__name__
        return 2
    finally:
        report["finished_at"] = now_utc().isoformat()
        _write(report)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def _write(report):
    with open(REPORT_PATH, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
