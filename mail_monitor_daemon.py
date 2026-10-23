"""Opt-in, local 60-second IMAP sensor. Never launches an ALDI provider action."""
import argparse
from datetime import datetime, timezone
import email
import hashlib
from email.utils import parsedate_to_datetime
import imaplib
import json
import os
import re
import signal
import ssl
import threading
import tempfile
from pathlib import Path
import time

from core.imap_sensor import SensorBlocked, SensorStore, fingerprint, positive_uid
from usage_mail_bridge import _mailboxes, _signal

MAX_BYTES = 1024 * 1024
BATCH = 100


def mailbox_key(key, config):
    _, host, port, user, _ = config
    return fingerprint(key, 'imap-mailbox-v1', host.casefold(), port, user, 'INBOX')


def _fetch(client, uid, fields, *, body=False):
    status, data = client.uid('fetch', str(uid), fields)
    if status != 'OK' or not data:
        raise OSError('imap_fetch_unavailable')
    if body:
        entries = [x for x in data if isinstance(x, tuple) and len(x) == 2
                   and isinstance(x[0], bytes) and isinstance(x[1], bytes)]
        if len(entries) != 1:
            raise SensorBlocked('imap_body_unverified')
        metadata, raw = entries[0]
    else:
        entries = [x for x in data if isinstance(x, bytes) and b'UID ' in x]
        if len(entries) != 1:
            raise SensorBlocked('imap_metadata_unverified')
        metadata, raw = entries[0], None
    identity = re.search(rb'\bUID ([0-9]+)\b', metadata)
    if identity is None or positive_uid(identity[1]) != uid:
        raise SensorBlocked('imap_uid_response_mismatch')
    return metadata, raw


def poll_mailbox(store, config, *, factory=imaplib.IMAP4_SSL, now=None):
    now = time.time() if now is None else now
    index, host, port, user, password = config
    mailbox = mailbox_key(store.key, config)
    counts = {'observed': 0, 'warnings': 0, 'blocked_candidates': 0, 'duplicates': 0}
    with factory(host, port, ssl_context=ssl.create_default_context(), timeout=20) as client:
        client.login(user, password)
        status, _ = client.select('INBOX', readonly=True)
        if status != 'OK':
            raise SensorBlocked('imap_folder_unavailable')
        _, validity = client.response('UIDVALIDITY')
        if not isinstance(validity, list) or len(validity) != 1:
            raise SensorBlocked('imap_uidvalidity_unverified')
        epoch = positive_uid(validity[0])
        last = store.attach(mailbox, epoch)
        cutoff = datetime.fromtimestamp(store.cutoff, timezone.utc)
        months = ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
        since = f'{cutoff.day:02}-{months[cutoff.month-1]}-{cutoff.year}'
        status, data = client.uid('search', None, 'UID', f'{last + 1}:*', 'SINCE', since)
        if status != 'OK' or not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], bytes):
            raise OSError('imap_search_unavailable')
        # Some servers treat n:* as a reversed range when n exceeds the largest
        # UID. Filter explicitly and process oldest first so a busy inbox cannot
        # starve earlier messages. Read and unread messages are both considered.
        uids = sorted({positive_uid(x) for x in data[0].split() if positive_uid(x) > last})[:BATCH]
        for uid in uids:
            metadata, _ = _fetch(client, uid, '(UID INTERNALDATE RFC822.SIZE)')
            size = re.search(rb'\bRFC822\.SIZE ([0-9]+)\b', metadata)
            received = re.search(rb'\bINTERNALDATE "([^"]+)"', metadata)
            if size is None or received is None:
                raise SensorBlocked('imap_metadata_unverified')
            try:
                stamp = parsedate_to_datetime(received[1].decode('ascii').replace('-', ' ', 2))
                if stamp.tzinfo is None:
                    raise ValueError
            except (ValueError, UnicodeError, TypeError):
                raise SensorBlocked('imap_received_time_unverified') from None
            outcome, semantic = 'IGNORED', fingerprint(store.key, 'imap-delivery-v1', mailbox, epoch, uid)
            if stamp.timestamp() > now + 300:
                raise SensorBlocked('imap_received_time_in_future')
            if stamp.timestamp() > store.cutoff:
                if int(size[1]) > MAX_BYTES:
                    # Refuse download; a bounded non-actionable observation.
                    outcome = 'BLOCKED'
                else:
                    _, raw = _fetch(client, uid, '(UID BODY.PEEK[])', body=True)
                    if len(raw) > MAX_BYTES or len(raw) != int(size[1]):
                        raise SensorBlocked('imap_message_size_mismatch')
                    message = email.message_from_bytes(raw)
                    ids = message.get_all('Message-ID', [])
                    material = ids[0].strip() if len(ids) == 1 and ids[0].strip() else None
                    semantic = fingerprint(store.key, 'imap-message-v1', material or hashlib.sha256(raw).hexdigest())
                    found = _signal(message)
                    if found == '80_percent': outcome = 'WARNING'
                    elif found == 'consumed': outcome = 'BLOCKED'
                    # Existing classifier is only a candidate detector, not a
                    # proof of mail authenticity, target SIM or booking authority.
            fresh = store.record(mailbox, epoch, uid, semantic, outcome)
            counts['observed'] += 1
            counts['duplicates'] += int(not fresh)
            counts['warnings'] += int(fresh and outcome == 'WARNING')
            counts['blocked_candidates'] += int(fresh and outcome == 'BLOCKED')
    return counts


def cycle(store, configs, *, factory=imaplib.IMAP4_SSL, now=None):
    now = time.time() if now is None else now
    reports = []
    for config in configs:
        mailbox = mailbox_key(store.key, config)
        store.register(mailbox)
        report = {'mailbox': config[0], 'state': 'IDLE', 'provider_action': False}
        if store.blocked(mailbox):
            report['state'] = 'BLOCKED'
        elif store.due(mailbox) > now:
            report['state'] = 'RETRY_WAIT'
        else:
            try:
                report.update(poll_mailbox(store, config, factory=factory, now=now))
                report['next_check_seconds'] = store.schedule(mailbox, now)
                if report['blocked_candidates']: report['state'] = 'BLOCKED'
            except (SensorBlocked, imaplib.IMAP4.error) as exc:
                if isinstance(exc, imaplib.IMAP4.abort):
                    report['state'] = 'RETRY_WAIT'
                    report['next_check_seconds'] = store.schedule(mailbox, now, failed=True)
                else:
                    store.block(mailbox)
                    report['state'] = 'BLOCKED'
            except (OSError, TimeoutError):
                report['state'] = 'RETRY_WAIT'
                report['next_check_seconds'] = store.schedule(mailbox, now, failed=True)
            except Exception:
                store.block(mailbox)
                report['state'] = 'BLOCKED'
        reports.append(report)
    return {'overall_status': 'BLOCKED', 'sensor_only': True, 'booking_enabled': False,
            'provider_action': False, 'mailboxes': reports}


def write_report(path, store, report):
    path = Path(path)
    if (not path.is_absolute() or path.is_symlink()
            or path.resolve() == store.path.resolve()
            or path.parent.resolve() != store.path.parent.resolve()):
        raise SensorBlocked('private_sensor_report_path_required')
    fd, temp = tempfile.mkstemp(prefix='.sensor-report-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(report, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--initialize', action='store_true', help='Explicit NEW sensor ledger only, never booking history')
    parser.add_argument('--cutoff', help='Approved aware UTC/offset timestamp for NEW ledger only')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--report', help='Sanitized heartbeat in the same private directory')
    parser.add_argument('--verify-backup', action='store_true', help='Local copy/reopen only, no network')
    args = parser.parse_args(argv)
    try:
        key = os.environ.get('ALDI_RECOVERY_KEY', '')
        if args.initialize:
            SensorStore.initialize(args.ledger, key, args.cutoff)
            print(json.dumps({'sensor_ledger_initialized': True, 'overall_status': 'BLOCKED', 'provider_action': False}))
            return 0
        if args.verify_backup:
            ok = SensorStore(args.ledger, key).verify_backup()
            print(json.dumps({'sensor_local_backup_verified': ok, 'overall_status': 'BLOCKED', 'provider_action': False}))
            return 0 if ok else 2
        # Opt-in is for IMAP reads only. There is no provider actor path here.
        if os.environ.get('ALDI_IMAP_MONITOR_ENABLED') != 'true':
            raise SensorBlocked('imap_monitor_disabled')
        store = SensorStore(args.ledger, key)
        configs = _mailboxes()
        if not configs: raise SensorBlocked('mailboxes_unavailable')
        stop = threading.Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        while not stop.is_set():
            report = cycle(store, configs)
            report['observed_at'] = datetime.now(timezone.utc).isoformat()
            if args.report: write_report(args.report, store, report)
            print(json.dumps(report, sort_keys=True), flush=True)
            if args.once:
                return 2 if any(x['state'] == 'BLOCKED' for x in report['mailboxes']) else 0
            stop.wait(60)
        return 0
    except Exception:
        # Fixed code only: exception text can contain passwords/hosts/UID data.
        print(json.dumps({'overall_status': 'BLOCKED', 'sensor_start_failed': True,
                          'provider_action': False, 'booking_enabled': False}), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
