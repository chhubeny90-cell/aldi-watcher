"""A fabricated positive certificate must not enable an unimplemented actor path."""
import json
from core.live_workflow_gate import assess_live_workflow
from scripts.check_live_workflow import main
from tests.test_release_status_hardening import ready, NOW, COMMIT


def test_even_complete_synthetic_readiness_cannot_invent_live_capabilities():
    result = assess_live_workflow(ready(), expected_commit=COMMIT,
                                  authorization_id='AUTH-SYNTHETIC', now=NOW)
    assert result['status'] == 'BLOCKED'
    assert result['booking_enabled'] is False
    assert 'mail_to_private_actor_unavailable' in result['reasons']
    assert 'operation_recovery_unverified' in result['reasons']


def test_wrong_commit_and_missing_specific_authorization_are_reported():
    result = assess_live_workflow(ready(), expected_commit='c' * 40,
                                  authorization_id='', now=NOW)
    assert 'workflow_commit_mismatch' in result['reasons']
    assert 'specific_authorization_missing' in result['reasons']


def test_missing_evidence_never_loads_credentials_or_starts_provider(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('ALDI_READINESS_EVIDENCE_PATH', str(tmp_path / 'absent'))
    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'BLOCKED' and report['provider_action'] is False
