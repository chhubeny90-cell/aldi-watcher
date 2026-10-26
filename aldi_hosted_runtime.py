"""Reuse an encrypted ALDI session and full booking journal on hosted runners."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile


class HostedRuntimeError(RuntimeError):
    """Contains only fixed local reason codes."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _context(mode):
    event = os.environ.get('GITHUB_EVENT_NAME')
    automatic_event = event == 'schedule' or event == 'workflow_run' and all((
        os.environ.get('ALDI_TRIGGER_WORKFLOW_NAME') == 'ALDI Usage Mail Monitor',
        os.environ.get('ALDI_TRIGGER_WORKFLOW_CONCLUSION') == 'success',
        os.environ.get('ALDI_TRIGGER_HEAD_REPOSITORY') == 'chhubeny90-cell/aldi-watcher',
        os.environ.get('ALDI_TRIGGER_HEAD_BRANCH') == 'main',
        os.environ.get('ALDI_TRIGGER_EVENT') in {'schedule', 'workflow_dispatch'},
    ))
    if (os.environ.get('GITHUB_REPOSITORY') != 'chhubeny90-cell/aldi-watcher'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_RUN_ATTEMPT') != '1'
            or not re.fullmatch(r'[0-9a-f]{40}', os.environ.get('GITHUB_SHA', ''))
            or not (automatic_event if mode == 'automatic' else event == 'workflow_dispatch')):
        raise HostedRuntimeError('controlled_context_required')
    expected_booking = 'true' if mode in {'refill', 'automatic'} else 'false'
    if os.environ.get('AUTO_BOOK_ENABLED') != expected_booking:
        raise HostedRuntimeError('booking_mode_mismatch')


def _sync_legacy(db):
    """Keep old actors blocked by our operations; never erase foreign guards."""
    from github_journal_state import consistent_mail_snapshot, _put_state, _snapshot_unresolved
    _, events, journal = consistent_mail_snapshot()
    if journal is None or any(event['phase'] in {'IN_FLIGHT', 'QUARANTINED_UNKNOWN'}
                              for event in events.values()):
        raise HostedRuntimeError('legacy_state_blocked')
    sha, state = journal
    with db._connect() as conn:
        known = {row[0] for row in conn.execute('SELECT recharge_id FROM recharges')}
    if any(operation['recharge_id'] not in known for operation in state['unresolved']):
        raise HostedRuntimeError('legacy_state_blocked')
    reserved = dict(state, unresolved=_snapshot_unresolved(db.db_path))
    if reserved == state:
        return
    _put_state(reserved, sha, message='Synchronize encrypted ALDI runtime guard [skip ci]')
    _, current_events, current = consistent_mail_snapshot()
    if current is None or current[1] != reserved or current_events != events:
        raise HostedRuntimeError('legacy_state_unconfirmed')


def _release_successful_auth(reservation):
    """Release only this worker's reservation after verified, durably saved login."""
    from github_journal_state import consistent_mail_snapshot, _put_state
    _, events, journal = consistent_mail_snapshot()
    if (journal is None or reservation.get('reservation_status') != 'confirmed'
            or journal[1]['auth_retry_after'] != reservation.get('retry_after')):
        raise HostedRuntimeError('auth_reservation_changed')
    sha, state = journal
    released = dict(state, auth_retry_after=None)
    _put_state(released, sha, message='Release successful saved ALDI session authentication guard [skip ci]')
    _, current_events, current = consistent_mail_snapshot()
    if current is None or current[1] != released or current_events != events:
        raise HostedRuntimeError('auth_release_unconfirmed')


def _cookie_records(jar):
    from core.aldi_http_login import ALLOWED_HOSTS
    domains = ALLOWED_HOSTS | {host.removeprefix('www.') for host in ALLOWED_HOSTS}
    return [{
        'name': cookie.name, 'value': cookie.value, 'domain': cookie.domain,
        'path': cookie.path or '/', 'secure': True, 'expires': cookie.expires,
        'domain_specified': cookie.domain_specified,
        'domain_initial_dot': cookie.domain_initial_dot,
        'rest': {key: value for key, value in cookie._rest.items()
                 if value is None or isinstance(value, str)},
    } for cookie in jar if cookie.domain.removeprefix('.').lower() in domains]


def _authenticate(state, account, password, report):
    import requests
    from core.aldi_http_login import AldiHttpLogin, LoginError
    from aldi_http_login_probe import _reserve_attempt
    client = AldiHttpLogin()
    reservation = None
    try:
        if state.cookies:
            for cookie in state.cookies:
                record = dict(cookie)
                domain_specified = record.pop('domain_specified')
                domain_initial_dot = record.pop('domain_initial_dot')
                restored = requests.cookies.create_cookie(**record)
                restored.domain_specified = domain_specified
                restored.domain_initial_dot = domain_initial_dot
                client.session.cookies.set_cookie(restored)
            try:
                client.verify_session(account)
                report['session_reused'] = True
            except LoginError as exc:
                # Only an actual redirect to the trusted login host proves expiry.
                # Network errors, unreadable data and a wrong SIM never resubmit credentials.
                if str(exc) != 'portal_session_unverified':
                    raise
                client.session.cookies.clear()
        if not report['session_reused']:
            reservation = {}
            try:
                _reserve_attempt(datetime.now(timezone.utc), reservation)
            finally:
                if 'retry_after' in reservation:
                    report['retry_after'] = reservation['retry_after']
            client.login(account, password)
        report['login_verified'] = True
        report['credential_submissions'] = client.report.get('credential_submissions', 0)
        state.save_cookies(_cookie_records(client.session.cookies))
        if reservation is not None:
            _release_successful_auth(reservation)
            report.pop('retry_after', None)
        return client
    except Exception:
        report['credential_submissions'] = client.report.get('credential_submissions', 0)
        client.close()
        raise


def _save_browser_cookies(state, client, driver):
    """Capture rotated portal cookies only after a verified account/status read."""
    import requests
    from urllib.parse import urlsplit
    from core.aldi_http_login import trusted_url, ALLOWED_HOSTS
    origin = urlsplit(trusted_url(driver.current_url)).hostname
    domains = ALLOWED_HOSTS | {host.removeprefix('www.') for host in ALLOWED_HOSTS}
    for cookie in driver.get_cookies():
        domain = cookie.get('domain', '').removeprefix('.').lower()
        if domain not in domains or not (origin == domain or origin.endswith('.' + domain)):
            continue
        restored = requests.cookies.create_cookie(
            name=cookie['name'], value=cookie['value'], domain=cookie['domain'],
            path=cookie.get('path') or '/', secure=True,
            expires=cookie.get('expiry'), rest={
                **({'HttpOnly': None} if cookie.get('httpOnly') else {}),
                **({'SameSite': cookie['sameSite']} if cookie.get('sameSite') else {}),
            })
        restored.domain_specified = cookie['domain'].startswith('.')
        restored.domain_initial_dot = restored.domain_specified
        client.session.cookies.set_cookie(restored)
    state.save_cookies(_cookie_records(client.session.cookies))


@contextmanager
def _refill_hooks(state, db, driver, live_report):
    import watcher
    import aldi_live_refill as live
    from core.database import Database
    original_begin = Database.begin_recharge
    original_set = Database.set_recharge_status

    def begin(self, *args, **kwargs):
        operation = original_begin(self, *args, **kwargs)
        state.save_journal(self.db_path)
        _sync_legacy(self)
        return operation

    def set_status(self, *args, **kwargs):
        result = original_set(self, *args, **kwargs)
        state.save_journal(self.db_path)
        _sync_legacy(self)
        return result

    replacements = [
        (Database, 'begin_recharge', begin), (Database, 'set_recharge_status', set_status),
        (live, 'open_live_journal', lambda: db), (live, 'REPORT_PATH', str(live_report)),
        (watcher, 'build_driver', lambda: driver),
        (watcher, 'aldi_login', lambda current: current is driver),
        (driver, 'quit', lambda: None),
    ]
    originals = [(obj, name, getattr(obj, name)) for obj, name, _ in replacements]
    try:
        for obj, name, value in replacements:
            setattr(obj, name, value)
        yield
    finally:
        for obj, name, value in reversed(originals):
            setattr(obj, name, value)


def _run(mode, report):
    import watcher
    import github_http_auth as browser_auth
    from core.aldi_http_login import phone_identifier
    from core.credentials import get_credential
    from github_encrypted_runtime import RuntimeState
    _context(mode)
    account = phone_identifier(os.environ.get('ALDI_EXPECTED_ACCOUNT'))
    if phone_identifier(get_credential('ALDI_USER')) != account:
        raise HostedRuntimeError('configured_account_mismatch')
    if mode in {'refill', 'automatic'}:
        from core.aldi_target import require_refill_target
        try:
            require_refill_target(account, os.environ.get('ALDI_EXPECTED_ACCOUNT', ''),
                                  os.environ.get('ALDI_REQUIRED_TARGET_SUFFIX', ''))
        except ValueError as exc:
            raise HostedRuntimeError(str(exc)) from None
    password = get_credential('ALDI_PASS')
    if not password or not watcher.configure_credentials('ALDI'):
        raise HostedRuntimeError('credentials_unavailable')
    state = RuntimeState()
    with tempfile.TemporaryDirectory(prefix='aldi-hosted-runtime-') as directory:
        journal_path = Path(directory) / 'journal.sqlite'
        if mode == 'initialize':
            state.initialize(account, journal_path)
            report['outcome'] = 'initialized'
            return 0
        state.load(account)
        db = state.restore_journal(journal_path)
        _sync_legacy(db)
        if mode == 'refill':
            state.authorize_first_refill()
        report['first_refill_authorized'] = state.first_refill_authorized
        client = None
        driver = None
        try:
            client = _authenticate(state, account, password, report)
            driver = watcher.build_driver()
            browser_auth.inject_verified_cookies(driver, client.session.cookies)
            watcher.navigate(driver, watcher.ALDI_OVERVIEW_URL, attempts=1)
            if not watcher.aldi_session_visible(driver):
                raise HostedRuntimeError('browser_session_unverified')
            report['automatic_enabled'] = state.refill_accepted
            should_book = mode == 'refill' or mode == 'automatic' and (
                state.refill_accepted or state.first_refill_authorized)
            if not should_book:
                import aldi_live_refill as live
                from core.aldi_refill import locate_selenium
                remaining, _ = live._bound_status(driver, account)
                evidence, control = locate_selenium(driver, remaining)
                report['status_verified'] = True
                report['free_refill_available'] = bool(evidence.get('refill_eligible') and control is not None)
                report['outcome'] = 'awaiting_first_refill' if mode == 'automatic' else 'observed'
                _save_browser_cookies(state, client, driver)
                return 0
            import aldi_live_refill_contract as contract
            report['booking_enabled'] = True
            live_report = Path(directory) / 'live-report.json'
            with _refill_hooks(state, db, driver, live_report):
                code = contract.main()
            result = json.loads(live_report.read_text())
            for name in ('booking_clicks', 'confirmation_clicks', 'successful_refills'):
                report[name] = result.get(name, 0)
            report['status_verified'] = result.get('status_success') is True
            report['outcome'] = result.get('outcome', 'runtime_error')
            evidence = contract._STATE.get('contract')
            if code == 0 and report['status_verified']:
                _save_browser_cookies(state, client, driver)
            if code == 0 and report['successful_refills'] > 0 and evidence is not None and evidence.success:
                state.accept_refill()
                report['automatic_enabled'] = True
            return code
        finally:
            try:
                if driver is not None:
                    driver.quit()
            finally:
                if client is not None:
                    client.close()


def render_summary(report):
    heading = '## ALDI-Sitzung und Gratis-Nachbuchung\n\n'
    if not isinstance(report, dict):
        return heading + ('**Ergebnis nicht bestätigt.** Bericht fehlt oder ist unlesbar. '
                          'Nach Abbruch den gespeicherten Zustand prüfen; nicht blind erneut buchen.\n')
    messages = {
        'initialized': 'Geschützter Sitzungs- und Buchungsspeicher eingerichtet. Noch kein Login oder Buchung.',
        'observed': 'Angemeldete Sitzung, Ziel-SIM und aktueller Status wurden geprüft. Keine Buchung angefordert.',
        'awaiting_first_refill': 'Sitzung und Status geprüft. Auto-Run wartet auf die erste bestätigte Gratis-Nachbuchung.',
        'refill_verified': 'Kostenlose 1-GB-Nachbuchung durch Anbieterbeleg bestätigt.',
        'run_limit_reached': 'Der begrenzte Nachbuchungslauf ist beendet; weitere Prüfungen folgen im Zeitplan.',
        'not_needed': 'Aktuell ist keine Nachbuchung nötig.',
        'free_refill_unavailable': 'Aktuell ist kein eindeutig kostenloser 1-GB-Refill freigegeben.',
        'auth_backoff_active': 'Der Abstand für einen neuen Passwort-Login ist noch aktiv. Keine neue Anmeldung gestartet.',
        'account_locked': 'ALDI meldet eine Kontosperre. Den Kontostatus über den offiziellen Weg klären.',
        'target_suffix_invalid': 'Das Repository-Secret ALDI_REQUIRED_TARGET_SUFFIX fehlt oder enthält nicht genau vier Ziffern. Es wurde kein ALDI-Zugriff gestartet.',
        'target_profile_mismatch': 'Die private Zielprüfung passt nicht zur konfigurierten Ziel-SIM. Es wurde kein ALDI-Zugriff gestartet.',
        'target_account_mismatch': 'Die konfigurierten Kontozuordnungen stimmen nicht überein. Es wurde kein ALDI-Zugriff gestartet.',
        'zero_price_unverified': 'Ein ausdrücklicher Nullpreis für diesen 1-GB-Refill ist nicht bestätigt. Es wurde kein weiterer Buchungs- oder Bestätigungsklick ausgelöst.',
        'runtime_initialization_required': 'Zuerst den Workflow einmal im Modus initialize starten.',
        'runtime_already_initialized': 'Der Speicher ist bereits eingerichtet. observe oder refill verwenden.',
        'runtime_encryption_key_required': 'Das Secret ALDI_STATE_ENCRYPTION_KEY fehlt oder hat ein ungültiges Format.',
        'target_suffix_invalid': 'Das Repository-Secret ALDI_REQUIRED_TARGET_SUFFIX muss genau vier Ziffern enthalten. Keine Anmeldung oder Buchung gestartet.',
        'target_profile_mismatch': 'Die konfigurierte Ziel-SIM passt nicht zur zusätzlichen Zielprüfung. Keine Anmeldung oder Buchung gestartet.',
        'runtime_initialized_state_missing': 'Der gespeicherte Buchungsverlauf fehlt. Nicht erneut initialisieren; Zustand wiederherstellen.',
        'unknown_after_click': 'Das Buchungsergebnis ist unklar. Der Vorgang bleibt gesperrt; keine automatische Wiederholung.',
        'unresolved_recharge_blocked': 'Ein ungeklärter Buchungsvorgang verhindert weitere Nachbuchungen.',
    }
    text = messages.get(report.get('outcome') if isinstance(report.get('outcome'), str) else None,
                        'Der Lauf konnte nicht bestätigt werden. Den gespeicherten Zustand und den bereinigten Bericht prüfen.')
    if report.get('session_reused') is True:
        text += '\n\nDie vorhandene Sitzung wurde ohne neuen Passwort-Login wiederverwendet.'
    if report.get('automatic_enabled') is True:
        text += '\n\nAuto-Run ist freigegeben und prüft stündlich sowie nach erfolgreicher Mailprüfung. GitHub kann Läufe verzögern.'
    elif report.get('first_refill_authorized') is True:
        text += '\n\nDie erste Gratis-Nachbuchung ist freigegeben. Falls aktuell nicht möglich, versucht der Zeitplan sie bei nächster bestätigter Verfügbarkeit. Nach Anbieterbestätigung folgen weitere automatisch.'
    if report.get('free_refill_available') is True:
        text += '\n\nEin kostenloser Refill wurde angeboten; zum ersten bestätigten Lauf den Modus refill verwenden.'
    retry = report.get('retry_after')
    if isinstance(retry, str):
        from aldi_http_login_summary import _utc_time
        retry = _utc_time(retry)
        if retry:
            text += '\n\nFrühester neuer Passwort-Login: **' + retry + '**. Eine gültige gespeicherte Sitzung kann weiter genutzt werden.'
    return heading + text + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['initialize', 'observe', 'refill', 'automatic'])
    parser.add_argument('--summary-only', action='store_true')
    args = parser.parse_args(argv)
    path = Path(os.getenv('ALDI_HOSTED_REPORT', 'aldi-hosted-report.json'))
    if args.summary_only:
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeError):
            report = None
        text = render_summary(report)
        if os.getenv('GITHUB_STEP_SUMMARY'):
            with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
                stream.write(text)
        else:
            print(text, end='')
        return 0
    if args.mode is None:
        parser.error('--mode is required')
    report = {'started_at': _now(), 'mode': args.mode, 'outcome': 'runtime_error',
              'session_reused': False, 'login_verified': False, 'status_verified': False,
              'booking_enabled': False, 'booking_clicks': 0, 'confirmation_clicks': 0,
              'successful_refills': 0, 'credential_submissions': 0, 'automatic_enabled': False}
    previous_umask = os.umask(0o077)
    try:
        return _run(args.mode, report)
    except Exception as exc:
        # Only our fixed error classes can supply a persisted reason. Never
        # expose arbitrary exception text, provider bodies or filesystem paths.
        from core.aldi_http_login import LoginError
        from github_encrypted_runtime import RuntimeStateError
        if isinstance(exc, (LoginError, RuntimeStateError, HostedRuntimeError)):
            report['outcome'] = str(exc)
        if args.mode == 'automatic' and report['outcome'] == 'auth_backoff_active':
            return 0
        return 2
    finally:
        report['finished_at'] = _now()
        path.write_text(json.dumps(report, sort_keys=True, indent=2), encoding='utf-8')
        print(json.dumps(report, sort_keys=True), flush=True)
        os.umask(previous_umask)


if __name__ == '__main__':
    raise SystemExit(main())
