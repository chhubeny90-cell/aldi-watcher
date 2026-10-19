"""Commit-bound readiness calculation. Never authorizes or starts a provider action."""
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit

STATUSES = ('BLOCKED', 'DRY_RUN_READY', 'LIVE_READY')
SCHEMA_VERSION = 3  # LIVE-010 adds a mandatory independent recovery proof
SECURITY = frozenset({'SECURITY', 'AUTH', 'SECRETS', 'BOOKING', 'JOURNAL', 'CAS'})
DRY = {f'DRY-{i:03d}': name for i, name in enumerate((
    'external actions disabled', 'synthetic mail replay', 'legacy deduplication',
    'archive crash safety', 'coherent snapshot', 'unknown blocks retries',
    'account and price rejection', 'sanitized reporting', 'complete regression suite'), 1)}
LIVE = {f'LIVE-{i:03d}': name for i, name in enumerate((
    'current authenticated account and tariff', 'current explicit zero-price 1GB offer',
    'mailbox to SIM binding', 'durable private host and journal',
    'no pending or unknown operation', 'exact-commit CI and review',
    'real provider completion contract', 'one-shot authorization',
    'complete historical deduplication and durable audit',
    'independent provider recovery contract'), 1)}
BLOCK = {f'BLOCK-{i:03d}': name for i, name in enumerate((
    'missing criterion catalog', 'unknown criterion ID', 'unreviewed change',
    'stale security evidence', 'missing evidence URL', 'missing artifact',
    'missing log', 'commit mismatch', 'CI failure or mismatch', 'nonreproducible tests',
    'incomplete dry-run coverage', 'external actions enabled during dry run',
    'pending operation', 'unknown operation', 'journal missing or corrupt',
    'snapshot mismatch', 'account mismatch', 'tariff mismatch', 'offer ambiguity',
    'positive or unknown price', 'mailbox SIM mapping unknown', 'dedup history incomplete',
    'queue capacity unresolved', 'durable runner unavailable', 'completion contract unproven',
    'recovery contract unproven', 'one-shot authorization absent', 'durable audit unproven'), 1)}
TESTS = {'TEST-001', 'TEST-002', 'TEST-003', 'TEST-004'}
_SHA = re.compile(r'[0-9a-f]{40}\Z')


def _sha(value):
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _url(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _records(value, ids, field='id'):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        return None
    keys = [item.get(field) for item in value]
    if any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys) or set(keys) != set(ids):
        return None
    return value


def evaluate(data, *, now=None):
    """Validate supplied evidence, not the truth of remote URLs or provider data.

    The schema is deliberately versioned and incompatible with PR107's generic
    truthy list. Evidence needs independent collection/review; this pure function
    has no credentials, browser, journal writes or live actor integration.
    """
    def blocked(reason):
        return {'status': 'BLOCKED', 'reasons': [reason]}

    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data.get('schema_version') != SCHEMA_VERSION:
        return blocked('SCHEMA_INVALID')
    commit, snapshot = data.get('commit'), data.get('snapshot_version')
    if not _sha(commit) or not _sha(snapshot) or data.get('ci_commit') != commit:
        return blocked('COMMIT_OR_SNAPSHOT_INVALID')
    for name, ids in (('dry', DRY), ('live', LIVE)):
        values = data.get(name)
        if not isinstance(values, dict) or set(values) != set(ids) or any(type(v) is not bool for v in values.values()):
            return blocked('CRITERIA_INVALID')
    blockers = _records(data.get('blockers'), BLOCK)
    tests = _records(data.get('tests'), TESTS)
    if blockers is None or any(b.get('active') is not False for b in blockers):
        return blocked('BLOCKERS_UNRESOLVED')
    if tests is None or any(t.get('status') != 'BESTANDEN' or t.get('reproducible') is not True
                            or t.get('commit') != commit or not _url(t.get('url')) for t in tests):
        return blocked('TEST_PROOF_INVALID')
    changes = data.get('changes')
    if not isinstance(changes, list) or not changes or any(not isinstance(c, dict) for c in changes):
        return blocked('CHANGE_REVIEW_INVALID')
    change_ids = [c.get('id') for c in changes]
    if (any(not isinstance(cid, str) or not cid.strip() for cid in change_ids)
            or len(set(change_ids)) != len(change_ids)
            or any(c.get('status') != 'BEWERTET' or c.get('commit') != commit
                   or not isinstance(c.get('category'), str) or c.get('category') not in SECURITY | {'DOCS', 'TESTS'} for c in changes)):
        return blocked('CHANGE_REVIEW_INVALID')
    if (type(data.get('pending')) is not int or data['pending'] != 0
            or type(data.get('unknown')) is not int or data['unknown'] != 0
            or data.get('unresolved') is not False):
        return blocked('JOURNAL_UNRESOLVED')
    if data.get('external_actions_possible') is not False:
        return blocked('EXTERNAL_ACTIONS_NOT_DISABLED')
    evidence = data.get('evidence')
    if not isinstance(evidence, list) or not evidence or any(not isinstance(e, dict) for e in evidence):
        return blocked('EVIDENCE_INVALID')
    evidence_ids, criteria = set(), set()
    reference = now or datetime.now(timezone.utc)
    if not isinstance(reference, datetime) or reference.tzinfo is None:
        return blocked('TIME_INVALID')
    for proof in evidence:
        eid, criterion = proof.get('id'), proof.get('criterion')
        if (not isinstance(eid, str) or re.fullmatch(r'EVID-[0-9]{3,}', eid) is None
                or eid in evidence_ids or not isinstance(criterion, str)
                or criterion not in DRY.keys() | LIVE.keys() | BLOCK.keys()
                or criterion in criteria or proof.get('valid') is not True
                or proof.get('commit') != commit or proof.get('snapshot_version') != snapshot
                or not isinstance(proof.get('test_id'), str) or proof.get('test_id') not in TESTS
                or not all(_url(proof.get(k)) for k in ('url', 'artifact', 'log'))):
            return blocked('EVIDENCE_INVALID')
        if any(c['category'] in SECURITY for c in changes) and proof.get('revalidated') is not True:
            return blocked('EVIDENCE_REVALIDATION_REQUIRED')
        try:
            observed = datetime.fromisoformat(proof['observed_at'].replace('Z', '+00:00'))
            age = (reference - observed).total_seconds()
            if observed.tzinfo is None or not 0 <= age <= 86400:
                return blocked('EVIDENCE_STALE')
        except (KeyError, AttributeError, TypeError, ValueError):
            return blocked('EVIDENCE_STALE')
        evidence_ids.add(eid)
        criteria.add(criterion)
    if not (DRY.keys() | BLOCK.keys()).issubset(criteria) or not all(data['dry'].values()):
        return blocked('DRY_PROOF_INCOMPLETE')
    if not all(data['live'].values()):
        return {'status': 'DRY_RUN_READY', 'reasons': ['LIVE_CRITERIA_INCOMPLETE']}
    if (not set(LIVE).issubset(criteria) or any(data.get(flag) is not True for flag in (
            'live_authorization', 'provider_completion_contract_verified',
            'provider_recovery_contract_verified', 'account_binding_verified'))):
        return blocked('LIVE_PROOF_INCOMPLETE')
    # LIVE_READY describes pre-action readiness. A receipt for the operation
    # being authorized cannot exist yet. Its official receipt is still required
    # by the independent completion verifier before any SUCCESS is persisted.
    return {'status': 'LIVE_READY', 'reasons': []}


def audit(previous, current, *, commit, change_id, responsible, evidence_ids, snapshot_version, timestamp=None):
    """Create an audit record; callers must supply external append-only storage.

    The digest detects accidental changes only. It is not a signature and does
    not establish durable or tamper-proof audit storage.
    """
    if (previous not in STATUSES or not isinstance(current, dict) or current.get('status') not in STATUSES
            or not _sha(commit) or not _sha(snapshot_version)
            or not isinstance(change_id, str) or not change_id.strip()
            or not isinstance(responsible, str) or not responsible.strip()
            or not isinstance(evidence_ids, list) or not evidence_ids
            or any(not isinstance(e, str) or re.fullmatch(r'EVID-[0-9]{3,}', e) is None for e in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
            or not isinstance(current.get('reasons'), list)
            or any(not isinstance(r, str) or not r for r in current['reasons'])):
        raise ValueError('incomplete_audit')
    stamp = timestamp or datetime.now(timezone.utc).isoformat()
    try:
        if datetime.fromisoformat(stamp.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ValueError('invalid_audit_time') from None
    if previous == current['status']:
        return None
    record = {'timestamp': stamp, 'old_status': previous, 'new_status': current['status'],
              'rules': current['reasons'] or ['CRITERIA_MET'], 'commit': commit,
              'change_id': change_id, 'responsible': responsible, 'evidence_ids': evidence_ids,
              'snapshot_version': snapshot_version}
    record['sha256'] = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    return record
