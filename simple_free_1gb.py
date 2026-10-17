"""Retired unjournaled refill entrypoint; use ALDI Guarded Free Refill."""

import json


def main():
    # Fail before reading credentials, opening a browser or contacting ALDI.
    print(json.dumps({
        "outcome": "legacy_refill_disabled",
        "provider_action": False,
        "next_step": "use_guarded_free_refill_workflow",
    }), flush=True)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
