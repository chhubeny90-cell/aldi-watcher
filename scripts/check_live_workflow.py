#!/usr/bin/env python3
"""Check offline live prerequisites; never print raw evidence or private paths."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.live_workflow_gate import assess_live_workflow


def main():
    try:
        path = Path(os.environ.get('ALDI_READINESS_EVIDENCE_PATH', ''))
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise ValueError
        if path.stat().st_mode & 0o077:
            raise ValueError
        evidence = json.loads(path.read_text(encoding='utf-8'))
        report = assess_live_workflow(
            evidence, expected_commit=os.environ.get('GITHUB_SHA', ''),
            authorization_id=os.environ.get('ALDI_AUTHORIZATION_ID', ''),
        )
    except Exception:
        report = {'status': 'BLOCKED', 'reasons': ['private_readiness_evidence_unavailable'],
                  'provider_action': False, 'booking_enabled': False}
    print(json.dumps(report, sort_keys=True))
    return 2 if report['status'] != 'LIVE_READY' else 0


if __name__ == '__main__':
    raise SystemExit(main())
