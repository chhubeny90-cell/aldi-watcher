"""Offline IMAP fault tests with real on-disk SQLite; no external connections."""
from email.message import EmailMessage
from pathlib import Path
import imaplib
import json
import sqlite3
import pytest
from core.imap_sensor import SensorBlocked, SensorStore, fingerprint
import mail_monitor_daemon as daemon

KEY = 'synthetic-original-key'
CONFIG = (1, 'imap.example.invalid', 993, 'synthetic-user', 'synthetic-password')
NOW = 1792526400  # 2026-10-20, deterministic relative to fixtures below


def message(mid='one', date='Tue, 20 Oct 2026 09:00:00 +0000', signal='consumed'):
    mail = EmailMessage()
    mail['From'] = 'ALDI TALK <sender@example.invalid>'
    mail['Message-ID'] = '<' + mid + '@example.invalid>'
    mail['Date'] = date
    mail['Subject'] = '80 % Datenvolumen verbraucht' if signal == 'warning' else 'Datenvolumen aufgebraucht'
    mail.set_content('ALDI TALK Datenvolumen')
    return mail.as_bytes()


class FakeImap:
    epoch = b'10'
    messages = {1: message()}
    searched = b'1'
    internaldate = b'20-Oct-2026 10:00:00 +0000'
    fail_uid = None
    logins = 0
    fetches = []
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def login(self, *_): type(self).logins += 1
    def select(self, folder, readonly):
        assert folder == 'INBOX' and readonly is True
        return 'OK', []
    def response(self, name):
        assert name == 'UIDVALIDITY'
        return 'UIDVALIDITY', [self.epoch]
    def uid(self, command, *args):
        if command == 'search':
            assert 'UNSEEN' not in args and 'SINCE' in args
            return 'OK', [self.searched]
        uid, fields = int(args[0]), args[1]
        self.fetches.append((uid, fields))
        if self.fail_uid == uid: raise OSError('synthetic network failure')
        raw = self.messages[uid]
        metadata = b'1 (UID ' + str(uid).encode() + b' INTERNALDATE "' + self.internaldate + b'" RFC822.SIZE ' + str(len(raw)).encode() + b')'
        return ('OK', [(metadata, raw), b')']) if 'BODY.PEEK[]' in fields else ('OK', [metadata])


@pytest.fixture
def store(tmp_path):
    return SensorStore.initialize(tmp_path / 'sensor.sqlite', KEY, '2026-10-20T09:00:00Z')


@pytest.fixture(autouse=True)
def reset_imap():
    FakeImap.epoch=b'10'; FakeImap.messages={1:message()}; FakeImap.searched=b'1'
    FakeImap.internaldate=b'20-Oct-2026 10:00:00 +0000'; FakeImap.fail_uid=None
    FakeImap.logins=0; FakeImap.fetches=[]


def run(store, configs=None, now=NOW, factory=FakeImap):
    return daemon.cycle(store, configs or [CONFIG], factory=factory, now=now)


def test_consumed_is_persisted_but_never_ready_or_dispatched(store, monkeypatch):
    import usage_mail_bridge
    monkeypatch.setattr(usage_mail_bridge, '_dispatch', lambda *_: pytest.fail('no dispatch'))
    report = run(store)
    assert report['overall_status'] == 'BLOCKED' and report['provider_action'] is False
    assert report['mailboxes'][0]['blocked_candidates'] == 1
    assert report['mailboxes'][0]['state'] == 'BLOCKED'
    # A fresh object/process-equivalent reopens the ledger and filters server's
    # reversed UID range result instead of rereading the consumed message.
    restarted = SensorStore(store.path, KEY)
    report = run(restarted, now=NOW+60)
    assert report['mailboxes'][0]['observed'] == 0
    assert report['mailboxes'][0]['unresolved_candidates'] == 1
    assert report['mailboxes'][0]['state'] == 'BLOCKED'
    assert report['provider_action'] is False


def test_read_messages_are_not_missed_and_warning_never_becomes_candidate(store):
    FakeImap.messages={1:message(signal='warning')}
    report=run(store)['mailboxes'][0]
    assert report['warnings']==1 and report['blocked_candidates']==0


def test_message_id_survives_reimport_with_new_uid_and_changed_date(store):
    run(store)
    FakeImap.messages={2:message(date='Tue, 20 Oct 2026 10:01:00 +0000')}
    FakeImap.searched=b'2'
    report=run(SensorStore(store.path,KEY),now=NOW+60)['mailboxes'][0]
    assert report['duplicates']==1 and report['blocked_candidates']==0


def test_uidvalidity_change_persists_circuit_breaker_without_further_login(store):
    run(store); FakeImap.epoch=b'11'
    assert run(store,now=NOW+60)['mailboxes'][0]['state']=='BLOCKED'
    before=FakeImap.logins
    assert run(SensorStore(store.path,KEY),now=NOW+3600)['mailboxes'][0]['state']=='BLOCKED'
    assert FakeImap.logins==before


def test_missing_ledger_is_never_replaced(store):
    store.path.unlink()
    with pytest.raises(SensorBlocked): store.connect()
    assert not store.path.exists()


def test_key_rotation_does_not_reset_history(store):
    before=store.path.read_bytes()
    with pytest.raises(SensorBlocked, match='key_mismatch'): SensorStore(store.path,'different-key')
    assert store.path.read_bytes()==before


def test_network_backoff_survives_restart_and_mailboxes_are_independent(store):
    def offline(*_,**__): raise OSError('synthetic-password must not leak')
    first=run(store,factory=offline)['mailboxes'][0]
    assert first['next_check_seconds']==60
    assert run(SensorStore(store.path,KEY),now=NOW+1)['mailboxes'][0]['state']=='RETRY_WAIT'
    second=run(store,now=NOW+60,factory=offline)['mailboxes'][0]
    assert second['next_check_seconds']==120
    other=(2,'imap.example.invalid',993,'other-user','secret')
    assert run(store,[other],now=NOW+61)['mailboxes'][0]['blocked_candidates']==1


def test_auth_failure_is_not_automatically_retried(store):
    class BadLogin(FakeImap):
        def login(self,*_): raise imaplib.IMAP4.error('synthetic-password')
    report=run(store,factory=BadLogin)
    assert 'synthetic-password' not in json.dumps(report)
    assert report['mailboxes'][0]['state']=='BLOCKED'
    assert run(store,now=NOW+60)['mailboxes'][0]['state']=='BLOCKED'
    assert FakeImap.logins==0


def test_fetch_failure_does_not_skip_earlier_uid(store):
    FakeImap.messages={1:message('one'),2:message('two')};FakeImap.searched=b'2 1'
    FakeImap.fail_uid=1
    assert run(store)['mailboxes'][0]['state']=='RETRY_WAIT'
    mailbox=daemon.mailbox_key(KEY,CONFIG)
    assert store.attach(mailbox,10)==0
    FakeImap.fail_uid=None
    assert run(store,now=NOW+60)['mailboxes'][0]['blocked_candidates']==2


def test_old_internaldate_is_ignored_even_when_date_header_is_new(store):
    FakeImap.internaldate=b'19-Oct-2026 10:00:00 +0000'
    report=run(store)['mailboxes'][0]
    assert report['blocked_candidates']==0
    assert not any('BODY.PEEK' in fields for _,fields in FakeImap.fetches)


def test_uid_and_identity_collision_cannot_advance_cursor(store):
    mailbox=daemon.mailbox_key(KEY,CONFIG);store.register(mailbox);store.attach(mailbox,10)
    store.record(mailbox,10,1,'first','BLOCKED')
    with pytest.raises(SensorBlocked,match='immutable_uid'):
        store.record(mailbox,10,1,'other','BLOCKED')
    assert store.attach(mailbox,10)==1


def test_sqlite_abort_rolls_back_observation_and_cursor_together(store):
    mailbox=daemon.mailbox_key(KEY,CONFIG);store.register(mailbox);store.attach(mailbox,10)
    with sqlite3.connect(store.path) as conn:
        conn.execute("CREATE TRIGGER synthetic_abort BEFORE UPDATE ON mailboxes BEGIN SELECT RAISE(ABORT,'synthetic crash'); END")
    with pytest.raises(sqlite3.IntegrityError): store.record(mailbox,10,1,'first','BLOCKED')
    with sqlite3.connect(store.path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()==(0,)
        assert conn.execute('SELECT COUNT(*) FROM deliveries').fetchone()==(0,)
        conn.execute('DROP TRIGGER synthetic_abort')
    assert SensorStore(store.path,KEY).attach(mailbox,10)==0


def test_cli_defaults_to_no_network_without_opt_in(store,monkeypatch,capsys):
    monkeypatch.delenv('ALDI_IMAP_MONITOR_ENABLED',raising=False)
    assert daemon.main(['--ledger',str(store.path),'--once'])==2
    assert json.loads(capsys.readouterr().out)['provider_action'] is False
    assert FakeImap.logins==0


def test_initialization_never_overwrites_existing_or_accepts_naive_cutoff(store):
    with pytest.raises(FileExistsError): SensorStore.initialize(store.path,KEY,'2026-10-20T09:00:00Z')
    with pytest.raises(SensorBlocked): SensorStore.initialize(store.path.parent/'new.sqlite',KEY,'2026-10-20T09:00:00')


def test_local_backup_reopens_without_mutating_source(store):
    run(store)
    before=store.path.read_bytes()
    assert store.verify_backup()
    assert store.path.read_bytes()==before
    assert list(store.path.parent.iterdir())==[store.path]


def test_sanitized_report_is_atomic_and_never_overwrites_ledger(store):
    report=run(store);path=store.path.parent/'report.json'
    daemon.write_report(path,store,report)
    output=path.read_text()
    assert 'synthetic-password' not in output and 'synthetic-user' not in output
    assert json.loads(output)['overall_status']=='BLOCKED'
    with pytest.raises(SensorBlocked): daemon.write_report(store.path,store,report)
    assert SensorStore(store.path,KEY).cutoff==store.cutoff


def test_graceful_stop_waits_instead_of_busy_looping(store,monkeypatch,capsys):
    monkeypatch.setenv('ALDI_RECOVERY_KEY',KEY)
    monkeypatch.setenv('ALDI_IMAP_MONITOR_ENABLED','true')
    monkeypatch.setattr(daemon,'_mailboxes',lambda:[CONFIG])
    monkeypatch.setattr(daemon.signal,'signal',lambda *_: None)
    calls=[]
    class Stop:
        done=False
        def is_set(self): return self.done
        def set(self): self.done=True
        def wait(self,seconds): calls.append(seconds);self.set()
    monkeypatch.setattr(daemon.threading,'Event',Stop)
    monkeypatch.setattr(daemon,'cycle',lambda *_: {'overall_status':'BLOCKED','mailboxes':[],'provider_action':False})
    assert daemon.main(['--ledger',str(store.path)])==0
    assert calls==[60]
    assert json.loads(capsys.readouterr().out)['provider_action'] is False


def test_simultaneous_observers_commit_one_message_only(store):
    from concurrent.futures import ThreadPoolExecutor
    mailbox=daemon.mailbox_key(KEY,CONFIG);store.register(mailbox);store.attach(mailbox,10)
    def record(_): return SensorStore(store.path,KEY).record(mailbox,10,1,'same-message','BLOCKED')
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(record,range(2)))==[False,True]
    with sqlite3.connect(store.path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()==(1,)
        assert conn.execute('SELECT COUNT(*) FROM deliveries').fetchone()==(1,)


def test_lower_uid_from_concurrent_snapshot_is_not_lost(store):
    from concurrent.futures import ThreadPoolExecutor
    mailbox = daemon.mailbox_key(KEY, CONFIG)
    store.register(mailbox)
    store.attach(mailbox, 10)
    # Either observer may commit first. Both distinct UIDs require receipts.
    def record(item):
        uid, identity = item
        return SensorStore(store.path, KEY).record(mailbox, 10, uid, identity, 'BLOCKED')
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(record, [(2, 'higher'), (1, 'lower')])) == [True, True]
    assert store.attach(mailbox, 10) == 2
    with sqlite3.connect(store.path) as conn:
        assert conn.execute('SELECT uid FROM deliveries ORDER BY uid').fetchall() == [(1,), (2,)]
    assert SensorStore(store.path, KEY).record(mailbox, 10, 1, 'lower', 'BLOCKED') is False
    assert store.unresolved_candidate_count(mailbox) == 2


def test_exponential_backoff_caps_and_resets_after_success(store):
    def offline(*_,**__): raise OSError('unavailable')
    now=NOW;delays=[]
    for _ in range(7):
        delay=run(store,now=now,factory=offline)['mailboxes'][0]['next_check_seconds']
        delays.append(delay);now+=delay
    assert delays==[60,120,240,480,900,900,900]
    assert run(store,now=now)['mailboxes'][0]['next_check_seconds']==60


def test_bad_uidvalidity_never_advances_or_retries_credentials(store):
    FakeImap.epoch=b'0'
    assert run(store)['mailboxes'][0]['state']=='BLOCKED'
    assert FakeImap.logins==1
    FakeImap.epoch=b'10'
    assert run(SensorStore(store.path,KEY),now=NOW+3600)['mailboxes'][0]['state']=='BLOCKED'
    assert FakeImap.logins==1


def test_returned_uid_must_match_request_before_any_observation(store):
    class WrongUid(FakeImap):
        def uid(self,command,*args):
            status,data=super().uid(command,*args)
            if command=='fetch':
                data=[(x[0].replace(b'UID 1 ',b'UID 2 '),x[1]) if isinstance(x,tuple)
                      else x.replace(b'UID 1 ',b'UID 2 ') for x in data]
            return status,data
    assert run(store,factory=WrongUid)['mailboxes'][0]['state']=='BLOCKED'
    assert store.attach(daemon.mailbox_key(KEY,CONFIG),10)==0


def test_oversized_body_is_not_downloaded(store):
    class Large(FakeImap):
        def uid(self,command,*args):
            status,data=super().uid(command,*args)
            if command=='fetch' and 'BODY.PEEK[]' not in args[1]:
                data=[x.replace(str(len(self.messages[1])).encode()+b')',str(daemon.MAX_BYTES+1).encode()+b')') for x in data]
            return status,data
    assert run(store,factory=Large)['mailboxes'][0]['blocked_candidates']==1
    assert not any('BODY.PEEK' in f for _,f in FakeImap.fetches)


def test_backup_cli_never_needs_network_opt_in(store,monkeypatch,capsys):
    monkeypatch.setenv('ALDI_RECOVERY_KEY',KEY)
    monkeypatch.delenv('ALDI_IMAP_MONITOR_ENABLED',raising=False)
    assert daemon.main(['--ledger',str(store.path),'--verify-backup'])==0
    assert json.loads(capsys.readouterr().out)['sensor_local_backup_verified'] is True
    assert FakeImap.logins==0


def test_dual_monitor_advisory_survives_sensor_restart_without_dispatch(store):
    first = run(store)
    first_hint = first["dual_monitor_advisory"]
    assert first_hint["state"] == "VERIFICATION_REQUIRED"
    assert first_hint["unverified_mail_candidate"] is True
    assert first_hint["account_read_due_now"] is False
    assert first_hint["booking_authorized"] is False

    restarted = SensorStore(store.path, KEY)
    second = run(restarted, now=NOW + 60)
    assert second["mailboxes"][0]["unresolved_candidates"] == 1
    hint = second["dual_monitor_advisory"]
    assert hint["state"] == "VERIFICATION_REQUIRED"
    assert hint["account_poll_seconds"] is None
    assert hint["booking_authorized"] is False


def test_dual_monitor_advisory_for_clean_warning_does_not_open_provider(store):
    FakeImap.messages = {1: message(signal='warning')}
    result = run(store)
    assert result["dual_monitor_advisory"]["state"] == "VERIFICATION_REQUIRED"
    assert result["dual_monitor_advisory"]["account_read_due_now"] is False
    assert result["provider_action"] is False
