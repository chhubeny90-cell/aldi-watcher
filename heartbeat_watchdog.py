"""Fail when the durable ALDI watcher heartbeat is stale."""

import json
import os

from github_hardening_state import heartbeat_age_seconds


def main():
    threshold = int(os.environ.get("ALDI_HEARTBEAT_MAX_AGE_SECONDS", "1800"))
    threshold = max(300, min(86400, threshold))
    age = heartbeat_age_seconds()
    payload = {
        "heartbeat_present": age is not None,
        "heartbeat_age_seconds": None if age is None else round(age, 1),
        "threshold_seconds": threshold,
    }
    print(json.dumps(payload), flush=True)
    if age is None or age > threshold:
        raise SystemExit(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
