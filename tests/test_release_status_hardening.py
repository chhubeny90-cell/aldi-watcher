"""Synthetic release proofs are test fixtures, never operational certificates."""
from datetime import datetime, timezone, timedelta
import pytest
from core.release_status import DRY, LIVE, BLOCK, TESTS, SCHEMA_VERSION, evaluate, audit

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
COMMIT = 'a' * 40
SNAPSHOT = 'b' * 40
URL = 'https://github.com/example/test/actions/runs/1'


def ready(live=True):
    criteria = sorted(DRY.keys() | BLOCK.keys() | (LIVE.keys() if live else set()))
    return {'schema_version': SCHEMA_VERSION, 'commit': COMMIT, 'ci_commit': COMMIT, 'snapshot_version': SNAPSHOT,
            'dry': dict.fromkeys(DRY, True), 'live': dict.fromkeys(LIVE, live),
            'blockers': [{'id': b, 'active': False} for b in sorted(BLOCK)],
            'tests': [{'id': t, 'status': 'BESTANDEN', 'reproducible': True,
                       'commit': COMMIT, 'url': URL} for t in sorted(TESTS)],
            'changes': [{'id': 'CHG-001', 'category': 'BOOKING', 'status': 'BEWERTET', 'commit': COMMIT}],
            'pending': 0, 'unknown': 0, 'unresolved': False, 'external_actions_possible': False,
            'live_authorization': True, 'provider_completion_contract_verified': True,
            'provider_recovery_contract_verified': True, 'account_binding_verified': True,
            'evidence': [{'id': f'EVID-{i:03d}', 'criterion': criterion, 'valid': True,
                          'commit': COMMIT, 'snapshot_version': SNAPSHOT, 'test_id': 'TEST-001',
                          'url': URL, 'artifact': URL, 'log': URL, 'revalidated': True,
                          'observed_at': NOW.isoformat()} for i, criterion in enumerate(criteria, 1)]}


def check(data):
    return evaluate(data, now=NOW)['status']


def test_full_synthetic_live_contract():
    assert check(ready()) == 'LIVE_READY'


def test_explicit_incomplete_live_is_dry_only():
    assert check(ready(False)) == 'DRY_RUN_READY'


@pytest.mark.parametrize('data', [None, {}, [], True, {'schema_version': 99}])
def test_missing_schema_blocked(data):
    assert check(data) == 'BLOCKED'


@pytest.mark.parametrize('section', ['dry', 'live'])
@pytest.mark.parametrize('mode', ['missing', 'unknown', 'truthy'])
def test_criteria_must_match_fixed_catalog(section, mode):
    d = ready()
    key = next(iter(d[section]))
    if mode == 'missing': del d[section][key]
    elif mode == 'unknown': d[section]['INVENTED-001'] = True
    else: d[section][key] = 1
    assert check(d) == 'BLOCKED'


@pytest.mark.parametrize('section', ['blockers', 'tests'])
@pytest.mark.parametrize('mode', ['missing', 'duplicate', 'unknown'])
def test_all_required_record_ids_must_be_present(section, mode):
    d = ready()
    if mode == 'missing': d[section].pop()
    elif mode == 'duplicate': d[section].append(dict(d[section][0]))
    else: d[section][0]['id'] = 'INVENTED-001'
    assert check(d) == 'BLOCKED'


@pytest.mark.parametrize('field,value', [('pending', True), ('pending', 1), ('unknown', 1),
    ('unknown', '0'), ('unresolved', True), ('external_actions_possible', True),
    ('ci_commit', 'c' * 40), ('commit', 'short'), ('snapshot_version', None)])
def test_journal_and_commit_fail_closed(field, value):
    d = ready(); d[field] = value
    assert check(d) == 'BLOCKED'


@pytest.mark.parametrize('field,value', [('valid', 1), ('commit', 'c' * 40),
    ('snapshot_version', 'c' * 40), ('test_id', 'UNKNOWN'), ('criterion', 'LIVE-999'),
    ('revalidated', False), ('url', 'http://example.invalid'), ('artifact', ''), ('log', None),
    ('observed_at', '2020-01-01T00:00:00Z'), ('observed_at', '2026-10-19T00:00:00'),
    ('observed_at', (NOW + timedelta(hours=1)).isoformat())])
def test_bad_evidence_never_grants_readiness(field, value):
    d = ready(); d['evidence'][0][field] = value
    assert check(d) == 'BLOCKED'


def test_duplicate_evidence_rejected():
    d = ready(); d['evidence'].append(dict(d['evidence'][0]))
    assert check(d) == 'BLOCKED'


def test_missing_live_evidence_blocks_even_when_flags_true():
    d = ready(); d['evidence'] = [e for e in d['evidence'] if not e['criterion'].startswith('LIVE-')]
    assert check(d) == 'BLOCKED'


@pytest.mark.parametrize('flag', ['live_authorization', 'provider_completion_contract_verified',
                                'provider_recovery_contract_verified', 'account_binding_verified'])
def test_live_boolean_cannot_be_omitted(flag):
    d = ready(); del d[flag]
    assert check(d) == 'BLOCKED'


def test_unassessed_security_change_blocks():
    d = ready(); d['changes'][0]['status'] = 'OFFEN'
    assert check(d) == 'BLOCKED'


def test_active_blocker_blocks():
    d = ready(); d['blockers'][0]['active'] = True
    assert check(d) == 'BLOCKED'


def test_audit_has_commit_snapshot_rules_and_evidence():
    entry = audit('BLOCKED', {'status': 'DRY_RUN_READY', 'reasons': ['RULE-1']}, commit=COMMIT,
                  change_id='CHG-001', responsible='reviewer', evidence_ids=['EVID-001'],
                  snapshot_version=SNAPSHOT, timestamp=NOW.isoformat())
    assert entry['commit'] == COMMIT and entry['snapshot_version'] == SNAPSHOT
    assert entry['evidence_ids'] == ['EVID-001'] and entry['rules'] == ['RULE-1']
    assert len(entry['sha256']) == 64


def test_naive_audit_timestamp_rejected():
    with pytest.raises(ValueError, match='invalid_audit_time'):
        audit('BLOCKED', {'status': 'DRY_RUN_READY', 'reasons': []}, commit=COMMIT,
              change_id='CHG-001', responsible='reviewer', evidence_ids=['EVID-001'],
              snapshot_version=SNAPSHOT, timestamp='2026-10-19')


def test_first_run_readiness_does_not_fabricate_a_receipt():
    d = ready()
    d['provider_receipt_verified'] = False
    assert check(d) == 'LIVE_READY'


@pytest.mark.parametrize('flag', ['provider_completion_contract_verified',
                                 'provider_recovery_contract_verified'])
@pytest.mark.parametrize('value', [False, 1, 'true', None])
def test_receipt_cannot_replace_real_completion_and_recovery_contracts(flag, value):
    d = ready()
    d['provider_receipt_verified'] = True
    d[flag] = value
    assert check(d) == 'BLOCKED'


def test_old_receipt_based_schema_requires_explicit_migration():
    d = ready()
    d['schema_version'] = 1
    d['provider_receipt_verified'] = True
    assert check(d) == 'BLOCKED'


def test_recovery_contract_requires_separate_live_evidence():
    d = ready()
    d['evidence'] = [e for e in d['evidence'] if e['criterion'] != 'LIVE-010']
    # A true boolean and a completion contract do not prove recovery.
    assert d['provider_recovery_contract_verified'] is True
    assert check(d) == 'BLOCKED'


def test_completion_contract_cannot_be_reused_as_recovery():
    d = ready()
    completion = next(e for e in d['evidence'] if e['criterion'] == 'LIVE-007')
    recovery = next(e for e in d['evidence'] if e['criterion'] == 'LIVE-010')
    recovery['criterion'] = completion['criterion']
    assert check(d) == 'BLOCKED'
