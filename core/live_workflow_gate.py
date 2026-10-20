"""Offline rollout gate. No secrets, provider access, or authorization by consensus.

The queue-to-actor adapter and operation-bound recovery are not implemented and
verified. A configuration variable or supplied readiness payload cannot invent
those capabilities. Keep the manual workflow blocked until they exist.
"""
from core.release_status import evaluate


def assess_live_workflow(evidence, *, expected_commit, authorization_id, now=None):
    reasons = []
    decision = evaluate(evidence, now=now)
    if decision['status'] != 'LIVE_READY':
        reasons.append('readiness_not_verified')
    if not isinstance(evidence, dict) or evidence.get('commit') != expected_commit:
        reasons.append('workflow_commit_mismatch')
    # This identifier is a reference to the specific user's authorization;
    # it is never proof of authorization without the independently checked record.
    if not isinstance(authorization_id, str) or not authorization_id.startswith('AUTH-'):
        reasons.append('specific_authorization_missing')
    # Factual implementation gaps, not user-overridable runtime switches.
    reasons.extend(('mail_to_private_actor_unavailable', 'operation_recovery_unverified',
                    'selenium_pre_auth_lock_guard_unverified'))
    return {'status': 'BLOCKED', 'reasons': reasons, 'provider_action': False,
            'booking_enabled': False}
