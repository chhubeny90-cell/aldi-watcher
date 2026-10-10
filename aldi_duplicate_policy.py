"""Optional policy for repeated ALDI free-1GB attempts.

When explicitly enabled, a previous PENDING/UNKNOWN attempt no longer blocks the
next scheduled run. The next run must still re-authenticate and re-prove the
exact active account, exactly 1 GB, explicit 0 EUR/kostenlos wording, and one
enabled booking control before another click can occur.
"""

import argparse
import os
from pathlib import Path

from aldi_auto_refill import _atomic_json, load_state


def reset_for_duplicate_retry(state_path, plan_path):
    enabled = os.getenv('ALDI_ALLOW_DUPLICATE_FREE_REFILL', 'false').strip().lower() == 'true'
    if not enabled:
        return False

    state = load_state(state_path)
    if not state or state.get('status') not in {'PENDING', 'UNKNOWN'}:
        return False

    state.update(
        status='READY',
        attempt_id=None,
        before_remaining_gb=None,
        selector_digest=None,
        prepared_at=None,
        last_reason='duplicate_retry_explicitly_allowed',
    )
    _atomic_json(state_path, state)
    try:
        Path(plan_path).unlink(missing_ok=True)
    except Exception:
        pass
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default='.state/aldi-booking-state.json')
    parser.add_argument('--plan', default='.state/aldi-booking-plan.json')
    args = parser.parse_args(argv)
    changed = reset_for_duplicate_retry(args.state, args.plan)
    print('duplicate-retry-reset=' + ('true' if changed else 'false'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
