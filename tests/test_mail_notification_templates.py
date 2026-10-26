"""Synthetic provider phrases; no copied mailbox bodies or personal identifiers."""
from datetime import datetime, timezone
import base64
import copy
from email.message import EmailMessage
import imaplib
import json

import pytest

import usage_mail_bridge as bridge
import usage_mail_notify as notify
import core.mailbox_cursor as cursor_module
from tests.mail_test_support import RescanningCursor


SENDER = 'ALDI TALK <noreply@alditalk-kundenbetreuung.de>'


@pytest.fixture(autouse=True)
def notification_cursor(monkeypatch):
    monkeypatch.setattr(notify, 'MailboxCursor', RescanningCursor)


def mail(body, subject='Verbrauch deines Datenvolumens', sender=SENDER, html=False, identity='one'):
    msg = EmailMessage()
    msg['From'] = sender
    msg['Subject'] = subject
    msg['Message-ID'] = f'<{identity}@example.invalid>'
    msg['Date'] = 'Mon, 26 Oct 2026 00:00:00 +0000'
    msg.set_content(body, subtype='html' if html else 'plain')
    return msg


@pytest.mark.parametrize('body,expected', [
    ('Hinweis zu deiner bestehenden Tarifoption: Du hast 80% des Datenvolumens in der aktuellen Optionslaufzeit genutzt.', '80_percent'),
    ('Das Datenvolumen deines Tarifs oder einer Zusatz-Option ist verbraucht.', 'consumed'),
    ('Ihr Highspeed-Volumen ist vollständig aufgebraucht.', 'consumed'),
    ('Das Datenvolumen ist nicht verbraucht.', None),
    ('Du kannst zusätzliches Datenvolumen verbrauchen.', None),
])
def test_observed_warning_and_consumed_share_subject_but_have_distinct_meanings(body, expected):
    assert bridge._signal(mail(body)) == expected


@pytest.mark.parametrize('sender', [
    'ALDI TALK <attacker@example.invalid>',
    'ALDI TALK <attacker@alditalk-kundenbetreuung.de.attacker.invalid>',
    'ALDI TALK <one@alditalk-kundenbetreuung.de>, Other <two@example.invalid>',
    'ALDI TALK',
])
def test_brand_or_display_name_does_not_validate_sender(sender):
    assert bridge._signal(mail('Das Datenvolumen ist verbraucht.', sender=sender)) is None


def test_notification_without_authentication_results_is_only_a_notification():
    msg = mail('Das Datenvolumen ist verbraucht.')
    assert msg.get('Authentication-Results') is None
    assert bridge._signal(msg) == 'consumed'
    # These headers do not make a forged display-name sender a booking proof.
    msg.replace_header('From', 'ALDI TALK <attacker@example.invalid>')
    msg['Authentication-Results'] = 'forged.invalid; dmarc=pass'
    assert bridge._signal(msg) is None


def test_html_warning_is_decoded_while_script_and_attributes_are_ignored():
    msg = mail('<div>Du hast <b>80</b>&nbsp;% des Datenvolumens genutzt.</div>'
               '<script>Das Datenvolumen ist verbraucht.</script>', html=True)
    assert bridge._signal(msg) == '80_percent'
    msg = mail('<a title="80% Datenvolumen">Das Datenvolumen ist verbraucht.</a>', html=True)
    assert bridge._signal(msg) == 'consumed'


def test_attached_or_forwarded_mail_does_not_create_usage_signal():
    msg = mail('Hier ist eine alte Nachricht.', subject='Weiterleitung')
    msg.add_attachment(mail('Das Datenvolumen ist verbraucht.'))
    assert bridge._signal(msg) is None
    assert bridge._signal(mail('Das Datenvolumen ist verbraucht.', subject='Re: Verbrauch deines Datenvolumens')) is None


@pytest.mark.parametrize('body,subject,expected', [
    ('Deine Bestellung wird bearbeitet. Das Datenvolumen ist verbraucht.', 'Deine Bestellung', None),
    ('Bestellung erhalten. Dein Datenvolumen ist verbraucht.', 'Deine Bestellung', 'order_received'),
    ('Die Bestellung deiner eSIM war erfolgreich.', 'Erfolgreiche Bestellung deiner eSIM', 'order_received'),
    ('Deine Zusatz-Option wurde erfolgreich aktiviert.', 'Buchung deiner Zusatz-Option', 'option_confirmation'),
    ('Deine kostenlose 1 GB Nachbuchung wurde erfolgreich aktiviert.', 'Bestätigung deiner Nachbuchung', 'refill_confirmation'),
    ('Deine kostenlose 1 GB Nachbuchung wurde nicht erfolgreich aktiviert.', 'Bestätigung deiner Nachbuchung', None),
])
def test_order_acceptance_generic_addon_and_refill_completion_are_not_consumption(body, subject, expected):
    assert bridge._signal(mail(body, subject=subject)) == expected


class ReadonlyUIDInbox:
    messages = []
    calls = []

    def __init__(self, *args, **kwargs):
        assert kwargs['timeout'] == 20

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, *args):
        self.calls.append(('login',))
        return 'OK', []

    def select(self, name, readonly):
        assert name == 'INBOX' and readonly is True
        self.calls.append(('select', readonly))
        return 'OK', [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == 'search':
            assert 'UNSEEN' not in args and 'SINCE' in args and 'FROM' in args
            return 'OK', [b' '.join(str(i + 1).encode() for i in range(len(self.messages)))]
        assert command == 'fetch' and args[1] == '(BODY.PEEK[])'
        return 'OK', [(b'BODY[]', self.messages[int(args[0]) - 1].as_bytes())]


def test_read_messages_are_scanned_with_uid_and_repeats_remain_distinct_deliveries(monkeypatch):
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'synthetic-test-key')
    ReadonlyUIDInbox.calls = []
    ReadonlyUIDInbox.messages = [mail('Das Datenvolumen ist verbraucht.', identity=str(i)) for i in range(8)]
    monkeypatch.setattr(notify.imaplib, 'IMAP4_SSL', ReadonlyUIDInbox)
    seen = set()
    def enqueue(key, signal, **kwargs):
        if key in seen:
            return False
        seen.add(key)
        return True
    def forbidden(*args, **kwargs):
        pytest.fail('No legacy claim or provider operation for consumed notifications')
    first = notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                             enqueue=enqueue, claim=forbidden)
    second = notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                              enqueue=enqueue, claim=forbidden)
    assert len(first) == 8 and len(seen) == 8
    assert second == []
    assert all(item['signal'] == 'consumed' for item in first)
    assert all(call[0] in {'login', 'select', 'search', 'fetch'} for call in ReadonlyUIDInbox.calls)


def test_confirmations_are_durably_deduped_but_never_enqueued(monkeypatch):
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'synthetic-test-key')
    ReadonlyUIDInbox.calls = []
    ReadonlyUIDInbox.messages = [mail('Deine kostenlose 1 GB Nachbuchung wurde erfolgreich aktiviert.',
                                    subject='Bestätigung deiner Nachbuchung')]
    monkeypatch.setattr(notify.imaplib, 'IMAP4_SSL', ReadonlyUIDInbox)
    monkeypatch.setattr(notify, '_legacy_seen', lambda *args: False)
    seen = set()
    def claim(key):
        if key in seen:
            return False
        seen.add(key)
        return True
    def forbidden(*args, **kwargs):
        pytest.fail('Mail confirmation must not reserve or resolve provider operation')
    alerts = notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic', claim=claim, enqueue=forbidden)
    assert alerts == [{'mailbox': 1, 'signal': 'refill_confirmation', 'actionable': False}]
    assert notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic', claim=claim, enqueue=forbidden) == []


def test_missing_dedup_key_probes_connection_without_reading_mail_or_writing_state(monkeypatch, tmp_path):
    monkeypatch.delenv('ALDI_RECOVERY_KEY', raising=False)
    monkeypatch.setattr(notify, '_mailboxes', lambda: [(1, 'imap.example.invalid', 993, 'private-user', 'private-password')])
    ReadonlyUIDInbox.calls = []
    monkeypatch.setattr(notify.imaplib, 'IMAP4_SSL', ReadonlyUIDInbox)
    path = tmp_path / 'report.json'
    monkeypatch.setattr(notify, 'REPORT_PATH', str(path))
    monkeypatch.setattr(notify, '_poll_one', lambda *a: pytest.fail('Message scan without dedup key'))
    assert notify.main() == 2
    report = json.loads(path.read_text())
    assert report['configuration_error'] == 'dedup_key_missing'
    assert report['mailbox_connectivity'] == [{'mailbox': 1, 'login_ok': True,
                                             'readonly_inbox_ok': True,
                                             'message_processing': False, 'error': None}]
    assert ReadonlyUIDInbox.calls == [('login',), ('select', True)]
    assert report['new_alerts'] == 0 and report['provider_action'] is False
    assert 'private-' not in path.read_text()


def test_probe_errors_are_fixed_classes_without_server_text(monkeypatch):
    class Broken(ReadonlyUIDInbox):
        def login(self, *args):
            raise imaplib.IMAP4.error('PRIVATE_SERVER_RESPONSE')
    monkeypatch.setattr(notify.imaplib, 'IMAP4_SSL', Broken)
    report = notify._probe_one(1, 'imap.example.invalid', 993, 'private-user', 'private-password')
    assert report['login_ok'] is False and report['readonly_inbox_ok'] is False
    assert report['error'] == 'IMAPError'
    assert 'PRIVATE' not in json.dumps(report) and 'private' not in json.dumps(report)


def test_state_key_derives_stable_domain_separated_mail_identity(monkeypatch):
    encoded = base64.urlsafe_b64encode(b's' * 32).decode()
    monkeypatch.delenv('ALDI_RECOVERY_KEY', raising=False)
    monkeypatch.setenv('ALDI_STATE_ENCRYPTION_KEY', encoded)
    assert notify._configure_dedup_key() == 'state_key'
    first = notify.os.environ['ALDI_RECOVERY_KEY']
    message = mail('Das Datenvolumen ist verbraucht.')
    identity = bridge._message_key(message, message.as_bytes())
    assert first != encoded and first != (b's' * 32).decode()
    monkeypatch.delenv('ALDI_RECOVERY_KEY')
    assert notify._configure_dedup_key() == 'state_key'
    assert notify.os.environ['ALDI_RECOVERY_KEY'] == first
    assert bridge._message_key(message, message.as_bytes()) == identity


def test_dedicated_mail_key_takes_precedence_over_state_key(monkeypatch):
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'synthetic-dedicated-mail-key')
    monkeypatch.setenv('ALDI_STATE_ENCRYPTION_KEY', 'invalid-state-key')
    assert notify._configure_dedup_key() == 'dedicated'
    assert notify.os.environ['ALDI_RECOVERY_KEY'] == 'synthetic-dedicated-mail-key'


@pytest.mark.parametrize('encoded', ['PRIVATE_INVALID_KEY', base64.urlsafe_b64encode(b's' * 31).decode()])
def test_invalid_state_key_fails_before_mailbox_or_state_access(monkeypatch, tmp_path, capsys, encoded):
    monkeypatch.delenv('ALDI_RECOVERY_KEY', raising=False)
    monkeypatch.setenv('ALDI_STATE_ENCRYPTION_KEY', encoded)
    monkeypatch.setattr(notify, '_mailboxes', lambda: pytest.fail('Mailbox access with invalid state key'))
    path = tmp_path / 'report.json'
    monkeypatch.setattr(notify, 'REPORT_PATH', str(path))
    assert notify.main() == 2
    report = json.loads(path.read_text())
    assert report['configuration_error'] == 'state_dedup_key_invalid'
    assert report['provider_action'] is False
    assert 'ALDI_RECOVERY_KEY' not in notify.os.environ
    assert encoded not in path.read_text() + capsys.readouterr().out


def test_portal_check_claims_notifications_without_creating_provider_queue_entries(monkeypatch):
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'synthetic-test-key')
    monkeypatch.setenv('ALDI_MAIL_TRIGGER_POLICY', 'portal_check')
    monkeypatch.setattr(notify, '_legacy_seen', lambda *args: False)
    monkeypatch.setattr(notify.handoff_queue, '_load', lambda: (None, {}))
    monkeypatch.setattr(notify.handoff_queue, '_archive', lambda: (None, {}))
    ReadonlyUIDInbox.calls = []
    ReadonlyUIDInbox.messages = [mail('Das Datenvolumen ist verbraucht.')]
    monkeypatch.setattr(notify.imaplib, 'IMAP4_SSL', ReadonlyUIDInbox)
    seen = set()
    def claim(key):
        if key in seen:
            return False
        seen.add(key)
        return True
    def forbidden(*args, **kwargs):
        pytest.fail('portal_check must not enqueue or complete provider operation')
    assert notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                            claim=claim, enqueue=forbidden) == [
                                {'mailbox': 1, 'signal': 'consumed', 'actionable': True}]
    assert notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                            claim=claim, enqueue=forbidden) == []


@pytest.mark.parametrize('location', ['queue', 'archive', 'legacy'])
@pytest.mark.parametrize('alias', ['current', 'legacy'])
def test_portal_check_preserves_existing_queue_archive_and_legacy_dedup(monkeypatch, location, alias):
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'synthetic-test-key')
    monkeypatch.setenv('ALDI_MAIL_TRIGGER_POLICY', 'portal_check')
    msg = mail('Das Datenvolumen ist verbraucht.')
    raw = msg.as_bytes()
    key = bridge._message_key(msg, raw) if alias == 'current' else bridge._legacy_message_key(msg, raw)
    record = {notify.handoff_queue._fingerprint(key): {'phase': 'RESERVED', 'revision': 0}}
    monkeypatch.setattr(notify, '_legacy_seen', lambda *args: location == 'legacy')
    monkeypatch.setattr(notify.handoff_queue, '_load', lambda: (None, record if location == 'queue' else {}))
    monkeypatch.setattr(notify.handoff_queue, '_archive', lambda: (None, record if location == 'archive' else {}))
    ReadonlyUIDInbox.calls = []
    ReadonlyUIDInbox.messages = [msg]
    monkeypatch.setattr(notify.imaplib, 'IMAP4_SSL', ReadonlyUIDInbox)
    def forbidden(*args, **kwargs):
        pytest.fail('Historical notification must not be replayed in new policy')
    assert notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                            claim=forbidden, enqueue=forbidden) == []


def test_mail_report_counts_confirmation_without_granting_booking_permission(monkeypatch, tmp_path, capsys):
    encoded = base64.urlsafe_b64encode(b's' * 32).decode()
    monkeypatch.delenv('ALDI_RECOVERY_KEY', raising=False)
    monkeypatch.setenv('ALDI_STATE_ENCRYPTION_KEY', encoded)
    monkeypatch.setenv('ALDI_MAIL_TRIGGER_POLICY', 'portal_check')
    monkeypatch.setattr(notify, '_mailboxes', lambda: [(1, 'imap.example.invalid', 993, 'private-user', 'private-password')])
    monkeypatch.setattr(notify, '_poll_one', lambda *args, **kwargs: [
        {'mailbox': 1, 'signal': signal, 'actionable': signal == 'consumed'}
        for signal in ('80_percent', 'consumed', 'refill_confirmation', 'option_confirmation', 'order_received')])
    path = tmp_path / 'report.json'
    monkeypatch.setattr(notify, 'REPORT_PATH', str(path))
    assert notify.main() == 0
    report = json.loads(path.read_text())
    assert report['new_alerts'] == 5 and report['actionable_alerts'] == 1
    assert report['early_warnings'] == report['refill_confirmations'] == 1
    assert report['option_confirmations'] == report['order_notifications'] == 1
    assert report['trigger_policy'] == 'portal_check'
    assert report['provider_check_requested'] is True
    assert report['booking_authorized'] is False and report['provider_action'] is False
    assert report['dedup_key_source'] == 'state_key'
    rendered = path.read_text() + capsys.readouterr().out
    assert encoded not in rendered and notify.os.environ['ALDI_RECOVERY_KEY'] not in rendered
    assert 'private-' not in rendered


def test_unavailable_uid_scan_is_a_failed_mailbox_not_an_empty_success(monkeypatch):
    class Inbox:
        def uid(self, *args):
            return 'NO', [b'PRIVATE_SERVER_MESSAGE']
    with pytest.raises(RuntimeError, match='^mailbox_uid_search_failed$'):
        RescanningCursor('imap.example.invalid', 'synthetic', Inbox()).batch()


class CursorInbox(ReadonlyUIDInbox):
    validity = b'11'
    fail_uid = None

    def response(self, name):
        if name == 'UIDVALIDITY':
            return name, [self.validity]
        assert name == 'UIDNEXT'
        return name, [str(len(self.messages) + 1).encode()]

    def uid(self, command, *args):
        if command == 'search':
            self.calls.append((command, *args))
            assert 'UNSEEN' not in args and 'FROM' in args
            return 'OK', [b' '.join(str(i + 1).encode() for i in range(len(self.messages)))]
        if args[0] == self.fail_uid:
            return 'NO', [b'PRIVATE_SERVER_MESSAGE']
        return super().uid(command, *args)


@pytest.fixture
def durable_notification_cursor(monkeypatch):
    state = {'sha': None, 'payload': None, 'writes': 0}
    def read(path):
        return None if state['payload'] is None else (state['sha'], copy.deepcopy(state['payload']))
    def write(path, payload, sha, **kwargs):
        assert sha == state['sha']
        state['writes'] += 1
        state['sha'] = str(state['writes'])
        state['payload'] = copy.deepcopy(payload)
    monkeypatch.setenv('ALDI_RECOVERY_KEY', 'synthetic-test-key')
    monkeypatch.setattr(cursor_module, '_read_json', read)
    monkeypatch.setattr(cursor_module, '_write_json', write)
    monkeypatch.setattr(notify, 'MailboxCursor', cursor_module.MailboxCursor)
    monkeypatch.setattr(notify.imaplib, 'IMAP4_SSL', CursorInbox)
    CursorInbox.calls = []
    CursorInbox.fail_uid = None
    CursorInbox.validity = b'11'
    return state


def test_notifier_preserves_more_than_one_batch_across_restarts(durable_notification_cursor):
    CursorInbox.messages = [mail('Das Datenvolumen ist verbraucht.', identity=str(i)) for i in range(75)]
    deliveries = set()
    def enqueue(key, signal, **kwargs):
        assert key not in deliveries
        deliveries.add(key)
        return True
    scans = []
    first = notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                             enqueue=enqueue, scan_reports=scans)
    second = notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                              enqueue=enqueue, scan_reports=scans)
    third = notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                             enqueue=enqueue, scan_reports=scans)
    assert (len(first), len(second), len(third)) == (50, 25, 0)
    assert len(deliveries) == 75
    assert [scan['pending_messages'] for scan in scans] == [25, 0, 0]
    record = next(iter(durable_notification_cursor['payload']['mailboxes'].values()))
    assert record['last_uid'] == 75


def test_notifier_fetch_failure_does_not_advance_cursor_and_retry_dedups(durable_notification_cursor):
    CursorInbox.messages = [mail('Das Datenvolumen ist verbraucht.', identity=str(i)) for i in range(2)]
    CursorInbox.fail_uid = b'2'
    deliveries = set()
    def enqueue(key, signal, **kwargs):
        new = key not in deliveries
        deliveries.add(key)
        return new
    with pytest.raises(RuntimeError, match='mailbox_uid_fetch_failed'):
        notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic', enqueue=enqueue)
    assert durable_notification_cursor['writes'] == 0 and len(deliveries) == 1
    CursorInbox.fail_uid = None
    alerts = notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic', enqueue=enqueue)
    assert len(alerts) == 1 and len(deliveries) == 2
    record = next(iter(durable_notification_cursor['payload']['mailboxes'].values()))
    assert record['last_uid'] == 2


def test_uidvalidity_change_rescans_without_discarding_message_dedup(durable_notification_cursor):
    CursorInbox.messages = [mail('Das Datenvolumen ist verbraucht.')]
    deliveries = set()
    def enqueue(key, signal, **kwargs):
        new = key not in deliveries
        deliveries.add(key)
        return new
    assert len(notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic', enqueue=enqueue)) == 1
    CursorInbox.validity = b'12'
    scans = []
    assert notify._poll_one(1, 'imap.example.invalid', 993, 'synthetic', 'synthetic',
                            enqueue=enqueue, scan_reports=scans) == []
    assert len(deliveries) == 1 and scans[0]['uidvalidity_changed'] is True
