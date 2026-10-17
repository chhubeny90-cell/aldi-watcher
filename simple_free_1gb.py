"""Simple ALDI TALK free 1 GB high-speed refill watcher.

Runs one check per GitHub Actions job:
1. Log in.
2. Reload the protected overview page.
3. Read remaining high-speed volume.
4. If it is below 1 GB, click only the uniquely verified free 1 GB refill control.
5. Reload and report the resulting remaining volume.
"""

import json
import time

import watcher
from core.aldi_refill import locate_selenium


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main():
    if not watcher.configure_credentials("ALDI"):
        emit({"outcome": "credentials_unavailable"})
        return 3

    driver = None
    try:
        driver = watcher.build_driver()

        if not watcher.aldi_login(driver):
            emit({"outcome": "login_failed"})
            return 2

        status = watcher.aldi_read_status(driver, include_refill=False)
        remaining_gb = status.get("inland_frei_gb")
        emit({"outcome": "status_read", "remaining_gb": remaining_gb})

        if remaining_gb is None or remaining_gb >= 1.0:
            emit({"outcome": "no_booking_needed", "remaining_gb": remaining_gb})
            return 0

        result, control = locate_selenium(driver, remaining_gb)
        emit({"outcome": "refill_check", "refill": result})

        if not result.get("refill_eligible") or control is None:
            emit({"outcome": "booking_blocked", "reason": result.get("refill_reason")})
            return 2

        watcher.safe_click(driver, control)
        time.sleep(5)

        after = watcher.aldi_read_status(driver, include_refill=False)
        remaining_after_gb = after.get("inland_frei_gb")
        emit({
            "outcome": "booking_attempted",
            "remaining_before_gb": remaining_gb,
            "remaining_after_gb": remaining_after_gb,
        })
        return 0

    except Exception as exc:
        emit({"outcome": "error", "exception_type": type(exc).__name__})
        return 2
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
