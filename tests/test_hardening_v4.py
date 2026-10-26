import json
import uuid
from email.message import EmailMessage
from pathlib import Path

import github_hardening_state as hardening
import github_live_refill as hosted
import usage_mail_bridge as mail_bridge


def _hosted_env(monkeypatch, tmp_path):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('ALDI_REMOTE_JOURNAL', 'true')
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str((tmp_path / 'journal.db').resolve()))
    monkeypatch.setattr(hosted, '_journal_path', lambda: (tmp_path / 'journal.db').resolve())
    monkeypatch.setattr(hosted, '_claim_mail_trigger', lambda: True)
    monkeypatch.setattr(hosted, '_target_guard', lambda: None)


def test_manual_auth_once_bypasses_existing_backoff(tmp_path, monkeypatch):
    _hosted_env(monkeypatch, tmp_path)
    monkeypatch.setenv('ALDI_MANUAL_AUTH_ONCE', 'true')
    monkeypatch.setattr(hosted, 'auth_backoff_active', lambda: True)
    calls = []
    monkeypatch.setattr(hosted.live, 'main', lambda: calls.append('live') or 0)
    monkeypatch.setattr(hosted, '_report_outcome', lambda: 'not_needed')
    monkeypatch.setattr(hosted, 'clear_auth_backoff', lambda: True)

    assert hosted._main() == 0
    assert calls == ['live']


def test_provider_maintenance_gets_thirty_minute_backoff(tmp_path, monkeypatch):
    _hosted_env(monkeypatch, tmp_path)
    monkeypatch.setattr(hosted, 'auth_backoff_active', lambda: False)
    monkeypatch.setattr(hosted.live, 'main', lambda: 2)
    monkeypatch.setattr(hosted, '_report_outcome', lambda: 'provider_maintenance')
    delays = []
    monkeypatch.setattr(hosted, 'set_auth_backoff', lambda hours: delays.append(hours))

    assert hosted._main() == 2
    assert delays == [0.5]


def test_maintenance_classifier_precedes_account_lock(monkeypatch):
    monkeypatch.setattr(hosted.live, 'diagnostics', lambda *_: {
        'provider_indications': {'maintenance': True, 'account_locked': True}
    })
    assert hosted._provider_login_outcome(object()) == 'provider_maintenance'


def test_target_guard_rejects_different_configured_account(monkeypatch):
    monkeypatch.setenv('ALDI_EXPECTED_ACCOUNT', '01500000001')
    monkeypatch.setattr(hosted.watcher, 'configure_credentials', lambda *_: True)
    monkeypatch.setattr(hosted.watcher, 'ALDI_ACCOUNT_USER', '01500000002')
    assert hosted._target_guard() == 'target_account_mismatch'


def test_target_guard_accepts_same_account(monkeypatch):
    monkeypatch.setenv('ALDI_EXPECTED_ACCOUNT', '+49 150 0000001')
    monkeypatch.setattr(hosted.watcher, 'configure_credentials', lambda *_: True)
    monkeypatch.setattr(hosted.watcher, 'ALDI_ACCOUNT_USER', '01500000001')
    assert hosted._target_guard() is None


def test_recovery_proof_contains_no_plain_baseline_or_binding(monkeypatch):
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'unit-test-secret')
    recharge_id = str(uuid.uuid4())
    writes = []
    monkeypatch.setattr(hardening, '_recovery_state', lambda: ('sha-old', hardening._empty_recovery()))
    monkeypatch.setattr(
        hardening, '_write_json',
        lambda path, payload, current_sha=None, message=None: writes.append((path, payload, current_sha)),
    )

    hardening.set_recovery_proof(recharge_id, 0.25, ('account-signature', 'tariff-signature'))
    proof = writes[0][1]['operations'][recharge_id]
    encoded = json.dumps(proof)

    assert '0.25' not in encoded
    assert 'account-signature' not in encoded
    assert 'tariff-signature' not in encoded
    assert hardening.recover_before_gb(recharge_id, proof) == 0.25
    assert hardening.recovery_binding_matches(
        recharge_id, proof, ('account-signature', 'tariff-signature')) is True
    assert hardening.recovery_binding_matches(
        recharge_id, proof, ('other-account', 'tariff-signature')) is False


def test_recovery_without_official_receipt_does_not_query_volume_or_release_guard(monkeypatch):
    recharge_id = str(uuid.uuid4())
    def forbidden_volume_lookup(*_):
        raise AssertionError('An allowance read cannot reconcile a provider operation')
    monkeypatch.setattr(hosted, '_ORIGINAL_BOUND_STATUS', forbidden_volume_lookup)
    assert hosted._recover_recharge_status(object(), recharge_id) == 'UNKNOWN'


def test_usage_mail_recognizes_80_percent_and_consumed():
    msg = EmailMessage()
    msg['From'] = 'ALDI TALK <noreply@alditalk-kundenbetreuung.de>'
    msg['Subject'] = '80 % Datenvolumen verbraucht'
    msg.set_content('Ihr Highspeed-Volumen ist zu 80 % verbraucht.')
    assert mail_bridge._signal(msg) == '80_percent'

    msg2 = EmailMessage()
    msg2['From'] = 'ALDI TALK <noreply@alditalk-kundenbetreuung.de>'
    msg2['Subject'] = 'Datenvolumen aufgebraucht'
    msg2.set_content('Ihr Datenvolumen ist aufgebraucht.')
    assert mail_bridge._signal(msg2) == 'consumed'


def test_usage_mail_ignores_unrelated_mail():
    msg = EmailMessage()
    msg['From'] = 'shop@example.invalid'
    msg['Subject'] = '80 % Rabatt'
    msg.set_content('Nur heute.')
    assert mail_bridge._signal(msg) is None


def test_main_workflow_is_credential_free_public_monitoring_only():
    text = Path('.github/workflows/run.yml').read_text(encoding='utf-8')
    assert "cron: '7-59/15 * * * *'" in text
    assert "github.event_name == 'schedule'" in text
    assert 'portal_probe.py' in text
    assert 'repository_dispatch:' not in text
    assert 'github_live_refill' not in text
    assert 'ALDI_MANUAL_AUTH_ONCE:' not in text
    assert 'ALDI_EXPECTED_ACCOUNT:' not in text
    assert 'ALDI_PASS:' not in text
    assert "AUTO_BOOK_ENABLED: 'false'" in text


def test_usage_mail_monitor_is_notification_only_and_has_no_provider_credentials():
    mail = Path('.github/workflows/mail-trigger.yml').read_text(encoding='utf-8')
    assert "cron: '0 * * * *'" in mail
    assert 'usage_mail_notify.py' in mail
    assert 'ALDI_RECOVERY_KEY: ${{ secrets.ALDI_RECOVERY_KEY }}' in mail
    assert 'ALDI_PASS:' not in mail
    assert 'ALDI_PASS_ENC:' not in mail
    assert 'ALDI_USER:' not in mail
    assert 'repository_dispatch' not in mail
    assert 'Surface refill-ready mail or mailbox failure' in mail


def test_authenticated_status_probe_and_live_watchdog_remain_disabled():
    status = Path('.github/workflows/status-probe.yml').read_text(encoding='utf-8')
    watchdog = Path('.github/workflows/watchdog.yml').read_text(encoding='utf-8')
    assert 'ALDI Read-Only Status Probe (disabled)' in status
    assert 'Authenticated ALDI status probing is disabled.' in status
    assert 'ALDI Watcher Watchdog (paused)' in watchdog
    assert 'Live runner intentionally disabled' in watchdog
