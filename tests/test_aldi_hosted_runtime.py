"""Offline behavior and disclosure boundaries of the hosted session worker."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import aldi_hosted_runtime as runtime
import aldi_http_login_probe as probe
import core.aldi_http_login as http
from core.database import Database


ACCOUNT = '01520000000'
PASSWORD = 'PRIVATE_PASSWORD'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, 'request',
                        Mock(side_effect=AssertionError('unexpected network')))


@pytest.fixture
def controlled(monkeypatch):
    values = {
        'GITHUB_REPOSITORY': 'chhubeny90-cell/aldi-watcher',
        'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1',
        'GITHUB_SHA': 'a' * 40, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'AUTO_BOOK_ENABLED': 'false',
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.mark.parametrize('name,value', [
    ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_REF', 'refs/heads/feature'),
    ('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_RUN_ATTEMPT', '01'),
    ('GITHUB_SHA', 'short'), ('GITHUB_SHA', 'G' * 40),
    ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_EVENT_NAME', 'pull_request'),
    ('GITHUB_EVENT_NAME', 'schedule'),
])
def test_manual_context_is_restricted(controlled, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match='controlled_context_required'):
        runtime._context('observe')


@pytest.mark.parametrize('mode,event,booking', [
    ('initialize', 'workflow_dispatch', 'false'),
    ('observe', 'workflow_dispatch', 'false'),
    ('refill', 'workflow_dispatch', 'true'),
    ('automatic', 'schedule', 'true'),
])
def test_mode_and_booking_permission_must_match(controlled, monkeypatch, mode, event, booking):
    monkeypatch.setenv('GITHUB_EVENT_NAME', event)
    monkeypatch.setenv('AUTO_BOOK_ENABLED', booking)
    runtime._context(mode)
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true' if booking == 'false' else 'false')
    with pytest.raises(RuntimeError, match='booking_mode_mismatch'):
        runtime._context(mode)


def test_automatic_mode_cannot_be_selected_from_manual_dispatch(controlled, monkeypatch):
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    with pytest.raises(RuntimeError, match='controlled_context_required'):
        runtime._context('automatic')


@pytest.fixture
def authentication(monkeypatch):
    jar = requests.cookies.RequestsCookieJar()
    cookie = requests.cookies.create_cookie(
        name='session', value='PRIVATE_COOKIE', domain='www.alditalk-kundenportal.de',
        path='/', secure=True,
    )
    jar.set_cookie(cookie)
    state = SimpleNamespace(cookies=runtime._cookie_records(jar), save_cookies=Mock())
    client = SimpleNamespace(
        session=SimpleNamespace(cookies=requests.cookies.RequestsCookieJar()),
        verify_session=Mock(return_value=True), login=Mock(), close=Mock(),
        report={'credential_submissions': 0},
    )
    sequence = []
    def login(account, password):
        sequence.append('login')
        client.report['credential_submissions'] += 1
    client.login.side_effect = login
    reserve = Mock(side_effect=lambda now, report: sequence.append('reserve'))
    release = Mock(side_effect=lambda report: sequence.append('release'))
    state.save_cookies.side_effect = lambda records: sequence.append('saved')
    monkeypatch.setattr(http, 'AldiHttpLogin', lambda: client)
    monkeypatch.setattr(probe, '_reserve_attempt', reserve)
    monkeypatch.setattr(runtime, '_release_successful_auth', release)
    report = {'session_reused': False}
    return SimpleNamespace(state=state, client=client, reserve=reserve,
                           report=report, sequence=sequence, release=release)


def test_valid_saved_session_never_resubmits_password(authentication):
    case = authentication
    assert runtime._authenticate(case.state, ACCOUNT, PASSWORD, case.report) is case.client
    case.client.verify_session.assert_called_once_with(ACCOUNT)
    case.client.login.assert_not_called()
    case.reserve.assert_not_called()
    case.client.close.assert_not_called()
    assert case.report['session_reused'] is True
    assert case.report['credential_submissions'] == 0
    case.state.save_cookies.assert_called_once()


def test_confirmed_expiry_reserves_before_one_fresh_login(authentication):
    case = authentication
    case.client.verify_session.side_effect = http.LoginError('portal_session_unverified')
    runtime._authenticate(case.state, ACCOUNT, PASSWORD, case.report)
    assert case.sequence == ['reserve', 'login', 'saved', 'release']
    assert case.report['session_reused'] is False
    assert case.report['credential_submissions'] == 1
    case.client.login.assert_called_once_with(ACCOUNT, PASSWORD)


@pytest.mark.parametrize('reason', ['provider_http_error', 'account_mismatch',
                                     'protected_account_response_unverified'])
def test_ambiguous_or_wrong_account_session_never_causes_login(authentication, reason):
    case = authentication
    case.client.verify_session.side_effect = http.LoginError(reason)
    with pytest.raises(http.LoginError, match=reason):
        runtime._authenticate(case.state, ACCOUNT, PASSWORD, case.report)
    case.reserve.assert_not_called()
    case.client.login.assert_not_called()
    case.state.save_cookies.assert_not_called()
    case.client.close.assert_called_once()
    case.release.assert_not_called()


def test_missing_saved_session_cannot_bypass_active_auth_guard(authentication):
    case = authentication
    case.state.cookies = []
    def blocked(now, report):
        report['retry_after'] = '2026-10-26T22:48:21Z'
        raise http.LoginError('auth_backoff_active')
    case.reserve.side_effect = blocked
    with pytest.raises(http.LoginError, match='auth_backoff_active'):
        runtime._authenticate(case.state, ACCOUNT, PASSWORD, case.report)
    case.client.verify_session.assert_not_called()
    case.client.login.assert_not_called()
    assert case.report['retry_after'] == '2026-10-26T22:48:21Z'
    case.client.close.assert_called_once()


def test_cookie_persistence_failure_does_not_return_usable_client(authentication):
    case = authentication
    case.state.save_cookies.side_effect = RuntimeError('PRIVATE_WRITE_FAILURE')
    with pytest.raises(RuntimeError):
        runtime._authenticate(case.state, ACCOUNT, PASSWORD, case.report)
    case.client.close.assert_called_once()
    case.client.login.assert_not_called()
    case.release.assert_not_called()


def test_host_only_cookie_remains_host_only_after_restore(authentication):
    case = authentication
    case.state.cookies[0]['domain_specified'] = False
    case.state.cookies[0]['domain_initial_dot'] = False
    runtime._authenticate(case.state, ACCOUNT, PASSWORD, case.report)
    restored = next(iter(case.client.session.cookies))
    assert restored.domain_specified is False
    assert restored.domain_initial_dot is False
    assert case.state.save_cookies.call_args.args[0][0]['domain_specified'] is False


@pytest.mark.parametrize('domain,scoped', [
    ('.alditalk-kundenportal.de', True), ('www.alditalk-kundenportal.de', False),
])
def test_rotated_browser_cookie_is_saved_with_its_original_scope(domain, scoped, capsys):
    jar = requests.cookies.RequestsCookieJar()
    jar.set_cookie(requests.cookies.create_cookie(
        name='portal_session', value='PRIVATE_OLD_COOKIE', domain=domain, path='/portal', secure=True))
    client = SimpleNamespace(session=SimpleNamespace(cookies=jar))
    state = SimpleNamespace(save_cookies=Mock())
    driver = SimpleNamespace(
        current_url='https://www.alditalk-kundenportal.de/portal/auth/uebersicht/',
        get_cookies=Mock(return_value=[{
            'name': 'portal_session', 'value': 'PRIVATE_ROTATED_COOKIE', 'domain': domain,
            'path': '/portal', 'secure': False, 'expiry': 1900000000,
            'httpOnly': True, 'sameSite': 'Lax',
        }]),
    )
    runtime._save_browser_cookies(state, client, driver)
    state.save_cookies.assert_called_once()
    records = state.save_cookies.call_args.args[0]
    assert len(records) == 1
    assert records[0] == {
        'name': 'portal_session', 'value': 'PRIVATE_ROTATED_COOKIE', 'domain': domain,
        'path': '/portal', 'secure': True, 'expires': 1900000000,
        'domain_specified': scoped, 'domain_initial_dot': scoped,
        'rest': {'HttpOnly': None, 'SameSite': 'Lax'},
    }
    assert 'PRIVATE' not in capsys.readouterr().out


def test_merging_portal_cookies_keeps_http_login_domain_session():
    jar = requests.cookies.RequestsCookieJar()
    jar.set_cookie(requests.cookies.create_cookie(
        name='sso_session', value='PRIVATE_SSO', domain='login.alditalk-kundenbetreuung.de',
        path='/', secure=True))
    client = SimpleNamespace(session=SimpleNamespace(cookies=jar))
    state = SimpleNamespace(save_cookies=Mock())
    driver = SimpleNamespace(
        current_url='https://www.alditalk-kundenportal.de/portal/auth/uebersicht/',
        get_cookies=Mock(return_value=[{
            'name': 'portal_session', 'value': 'PRIVATE_PORTAL',
            'domain': '.alditalk-kundenportal.de', 'path': '/',
        }]),
    )
    runtime._save_browser_cookies(state, client, driver)
    assert {(row['name'], row['value']) for row in state.save_cookies.call_args.args[0]} == {
        ('sso_session', 'PRIVATE_SSO'), ('portal_session', 'PRIVATE_PORTAL'),
    }


@pytest.mark.parametrize('domain', [
    'attacker.invalid', '.alditalk-kundenportal.de.attacker.invalid',
    '.attacker.alditalk-kundenportal.de', 'alditalk-kundenportal.de.evil',
    '..alditalk-kundenportal.de', '.login.alditalk-kundenbetreuung.de',
])
def test_browser_cookies_from_unrelated_or_invalid_domains_are_ignored(domain):
    client = SimpleNamespace(session=SimpleNamespace(cookies=requests.cookies.RequestsCookieJar()))
    state = SimpleNamespace(save_cookies=Mock())
    driver = SimpleNamespace(
        current_url='https://www.alditalk-kundenportal.de/portal/auth/uebersicht/',
        get_cookies=Mock(return_value=[{'name': 'hostile', 'value': 'PRIVATE_HOSTILE',
                                      'domain': domain, 'path': '/'}]),
    )
    runtime._save_browser_cookies(state, client, driver)
    assert state.save_cookies.call_args.args[0] == []


@pytest.mark.parametrize('url', [
    'http://www.alditalk-kundenportal.de/portal/',
    'https://attacker.invalid/portal/',
    'https://www.alditalk-kundenportal.de.attacker.invalid/portal/',
    'https://user:PRIVATE_PASSWORD@www.alditalk-kundenportal.de/portal/',
])
def test_browser_cookie_save_rejects_untrusted_current_origin(url):
    client = SimpleNamespace(session=SimpleNamespace(cookies=requests.cookies.RequestsCookieJar()))
    state = SimpleNamespace(save_cookies=Mock())
    driver = SimpleNamespace(current_url=url, get_cookies=Mock())
    with pytest.raises(http.LoginError, match='unexpected_redirect_origin'):
        runtime._save_browser_cookies(state, client, driver)
    driver.get_cookies.assert_not_called()
    state.save_cookies.assert_not_called()


@pytest.fixture
def public_guard(monkeypatch):
    import github_journal_state as public
    state = {'version': 2, 'unresolved': [], 'auth_retry_after': '2026-10-26T22:48:21Z'}
    storage = {'state': state, 'sha': 'a' * 40}
    events = {}
    def snapshot():
        return copy.deepcopy(('b' * 40, events, (storage['sha'], storage['state'])))
    def write(value, sha, **kwargs):
        assert sha == storage['sha']
        storage['state'] = copy.deepcopy(value)
        storage['sha'] = 'c' * 40
    reads = Mock(side_effect=snapshot)
    writes = Mock(side_effect=write)
    monkeypatch.setattr(public, 'consistent_mail_snapshot', reads)
    monkeypatch.setattr(public, '_put_state', writes)
    return SimpleNamespace(storage=storage, events=events, reads=reads, writes=writes,
                           snapshot=snapshot, write=write)


def test_successful_auth_release_only_clears_its_confirmed_reservation(public_guard):
    guard = public_guard
    runtime._release_successful_auth({'reservation_status': 'confirmed',
                                      'retry_after': guard.storage['state']['auth_retry_after']})
    assert guard.storage['state'] == {'version': 2, 'unresolved': [], 'auth_retry_after': None}
    guard.writes.assert_called_once()
    assert guard.reads.call_count == 2


@pytest.mark.parametrize('reservation', [
    {}, {'reservation_status': 'unconfirmed', 'retry_after': '2026-10-26T22:48:21Z'},
    {'reservation_status': 'confirmed', 'retry_after': '2026-10-27T22:48:21Z'},
])
def test_successful_auth_cannot_clear_foreign_or_unconfirmed_reservation(public_guard, reservation):
    with pytest.raises(runtime.HostedRuntimeError, match='auth_reservation_changed'):
        runtime._release_successful_auth(reservation)
    public_guard.writes.assert_not_called()
    assert public_guard.storage['state']['auth_retry_after'] is not None


def test_auth_release_requires_confirmed_readback(public_guard):
    guard = public_guard
    first = guard.snapshot()
    guard.reads.side_effect = [first, first]
    with pytest.raises(runtime.HostedRuntimeError, match='auth_release_unconfirmed'):
        runtime._release_successful_auth({'reservation_status': 'confirmed',
                                          'retry_after': first[2][1]['auth_retry_after']})
    guard.writes.assert_called_once()


def test_legacy_guard_tracks_pending_and_terminal_journal_without_erasing_backoff(tmp_path, public_guard):
    db = Database(str(tmp_path / 'journal.sqlite'))
    operation = db.begin_recharge('alditalk', ACCOUNT)
    retry = public_guard.storage['state']['auth_retry_after']
    runtime._sync_legacy(db)
    assert public_guard.storage['state']['unresolved'] == [{'recharge_id': operation, 'status': 'PENDING'}]
    assert public_guard.storage['state']['auth_retry_after'] == retry
    db.set_recharge_status(operation, 'SUCCESS')
    runtime._sync_legacy(db)
    assert public_guard.storage['state']['unresolved'] == []
    assert public_guard.storage['state']['auth_retry_after'] == retry


def test_legacy_guard_never_erases_foreign_unresolved_operation(tmp_path, public_guard):
    db = Database(str(tmp_path / 'journal.sqlite'))
    public_guard.storage['state']['unresolved'] = [{'recharge_id': 'foreign-operation', 'status': 'UNKNOWN'}]
    with pytest.raises(runtime.HostedRuntimeError, match='legacy_state_blocked'):
        runtime._sync_legacy(db)
    public_guard.writes.assert_not_called()


@pytest.mark.parametrize('phase', ['IN_FLIGHT', 'QUARANTINED_UNKNOWN'])
def test_legacy_guard_rejects_in_flight_mail_actor(tmp_path, public_guard, phase):
    db = Database(str(tmp_path / 'journal.sqlite'))
    public_guard.events['event'] = {'phase': phase}
    with pytest.raises(runtime.HostedRuntimeError, match='legacy_state_blocked'):
        runtime._sync_legacy(db)
    public_guard.writes.assert_not_called()


def test_pending_snapshot_and_legacy_guard_are_durable_before_booking(tmp_path, monkeypatch):
    import watcher
    import aldi_live_refill as live
    db = Database(str(tmp_path / 'journal.sqlite'))
    sequence = []
    state = SimpleNamespace(save_journal=Mock(side_effect=lambda path: sequence.append('encrypted')))
    monkeypatch.setattr(runtime, '_sync_legacy', lambda db: sequence.append('legacy'))
    driver = SimpleNamespace(quit=Mock())
    original_driver = watcher.build_driver
    with runtime._refill_hooks(state, db, driver, tmp_path / 'report.json'):
        operation = db.begin_recharge('alditalk', ACCOUNT)
        sequence.append('click')
        assert watcher.build_driver() is driver
        assert live.open_live_journal() is db
    assert sequence == ['encrypted', 'legacy', 'click']
    assert db.get_unresolved_recharges()[0].recharge_id == operation
    assert watcher.build_driver is original_driver


def test_uncertain_snapshot_blocks_click_and_restores_global_hooks(tmp_path, monkeypatch):
    import watcher
    db = Database(str(tmp_path / 'journal.sqlite'))
    state = SimpleNamespace(save_journal=Mock(side_effect=RuntimeError('uncertain')))
    legacy = Mock()
    monkeypatch.setattr(runtime, '_sync_legacy', legacy)
    click = Mock()
    driver = SimpleNamespace(quit=Mock())
    original_driver = watcher.build_driver
    with pytest.raises(RuntimeError, match='uncertain'):
        with runtime._refill_hooks(state, db, driver, tmp_path / 'report.json'):
            db.begin_recharge('alditalk', ACCOUNT)
            click()
    click.assert_not_called()
    legacy.assert_not_called()
    assert db.get_unresolved_recharges()[0].status == 'PENDING'
    assert watcher.build_driver is original_driver


def test_provider_receipt_is_saved_with_terminal_journal_snapshot(tmp_path, monkeypatch):
    import aldi_live_refill_contract as contract
    db = Database(str(tmp_path / 'journal.sqlite'))
    snapshots = []
    def snapshot(path):
        with sqlite3.connect(path) as conn:
            statuses = conn.execute('SELECT status FROM recharges').fetchall()
            evidence = conn.execute("SELECT name FROM sqlite_master WHERE name='recharge_provider_evidence'").fetchone()
            receipts = conn.execute('SELECT provider_operation_id FROM recharge_provider_evidence').fetchall() if evidence else []
        snapshots.append((statuses, receipts))
    state = SimpleNamespace(save_journal=Mock(side_effect=snapshot))
    monkeypatch.setattr(runtime, '_sync_legacy', lambda db: None)
    driver = SimpleNamespace(quit=Mock())
    contract._reset_state()
    try:
        with runtime._refill_hooks(state, db, driver, tmp_path / 'report.json'):
            hooks = contract._install_hooks()
            try:
                operation = db.begin_recharge('alditalk', ACCOUNT)
                contract._STATE.update(
                    pre_binding=('account', 'tariff'), post_binding=('account', 'tariff'),
                    exchange=SimpleNamespace(
                        request_payload={'updateOfferResourceID': 'PRIVATE_RESOURCE',
                                         'offerId': 'offer', 'subscriptionId': 'subscription'},
                        response_payload={'operationId': 'PRIVATE_OPERATION',
                                          'resourceId': 'PRIVATE_RESOURCE', 'status': 'completed'},
                        http_status=200, request_was_update_unlimited=True,
                    ),
                )
                assert db.set_recharge_status(operation, 'UNKNOWN') == 'SUCCESS'
            finally:
                contract._restore_hooks(hooks)
    finally:
        contract._reset_state()
    assert snapshots[0] == ([('PENDING',)], [])
    assert snapshots[-1] == ([('SUCCESS',)], [('PRIVATE_OPERATION',)])


@pytest.fixture
def worker(tmp_path, monkeypatch, controlled):
    import watcher
    import github_http_auth
    import github_encrypted_runtime
    import core.credentials
    import aldi_live_refill as live
    import core.aldi_refill
    import aldi_live_refill_contract as contract
    db = Database(str(tmp_path / 'private.sqlite'))
    state = SimpleNamespace(refill_accepted=False, first_refill_authorized=False,
                            load=Mock(), restore_journal=Mock(return_value=db),
                            initialize=Mock(), accept_refill=Mock(), save_journal=Mock())
    state.authorize_first_refill = Mock(side_effect=lambda: setattr(state, 'first_refill_authorized', True))
    monkeypatch.setattr(github_encrypted_runtime, 'RuntimeState', lambda: state)
    monkeypatch.setenv('ALDI_EXPECTED_ACCOUNT', ACCOUNT)
    monkeypatch.setattr(core.credentials, 'get_credential', lambda name: ACCOUNT if name == 'ALDI_USER' else PASSWORD)
    monkeypatch.setattr(watcher, 'configure_credentials', lambda provider: True)
    monkeypatch.setattr(runtime, '_sync_legacy', Mock())
    client = SimpleNamespace(session=SimpleNamespace(cookies=[]), close=Mock())
    monkeypatch.setattr(runtime, '_authenticate', Mock(return_value=client))
    monkeypatch.setattr(runtime, '_save_browser_cookies', Mock())
    driver = SimpleNamespace(quit=Mock())
    monkeypatch.setattr(watcher, 'build_driver', lambda: driver)
    monkeypatch.setattr(github_http_auth, 'inject_verified_cookies', Mock())
    monkeypatch.setattr(watcher, 'navigate', Mock())
    monkeypatch.setattr(watcher, 'aldi_session_visible', lambda driver: True)
    monkeypatch.setattr(live, '_bound_status', lambda driver, account: (0.5, ('account', 'tariff')))
    monkeypatch.setattr(core.aldi_refill, 'locate_selenium', lambda driver, remaining: ({'refill_eligible': True}, object()))
    result = {'outcome': 'refill_verified', 'booking_clicks': 1, 'confirmation_clicks': 0,
              'successful_refills': 1, 'status_success': True}
    def refill():
        Path(live.REPORT_PATH).write_text(json.dumps(result))
        return 0 if result['outcome'] in {'refill_verified', 'not_needed', 'free_refill_unavailable'} else 2
    refill_mock = Mock(side_effect=refill)
    monkeypatch.setattr(contract, 'main', refill_mock)
    monkeypatch.setitem(contract._STATE, 'contract', SimpleNamespace(success=True))
    return SimpleNamespace(state=state, client=client, driver=driver, refill=refill_mock,
                           result=result, report={'session_reused': False})


def test_automatic_without_acceptance_observes_without_booking(worker, monkeypatch):
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'schedule')
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    assert runtime._run('automatic', worker.report) == 0
    worker.refill.assert_not_called()
    worker.state.accept_refill.assert_not_called()
    assert worker.report['outcome'] == 'awaiting_first_refill'
    assert worker.report['free_refill_available'] is True
    worker.client.close.assert_called_once()
    worker.driver.quit.assert_called_once()


def test_automatic_after_acceptance_can_run_one_guarded_refill(worker, monkeypatch):
    worker.state.refill_accepted = True
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'schedule')
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    assert runtime._run('automatic', worker.report) == 0
    worker.refill.assert_called_once()
    assert worker.report['automatic_enabled'] is True


def test_automatic_can_complete_previously_authorized_first_refill(worker, monkeypatch):
    worker.state.first_refill_authorized = True
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'schedule')
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    assert runtime._run('automatic', worker.report) == 0
    worker.refill.assert_called_once()
    worker.state.authorize_first_refill.assert_not_called()
    worker.state.accept_refill.assert_called_once()
    assert worker.report['automatic_enabled'] is True


def test_manual_authorization_survives_refill_not_yet_available(worker, monkeypatch):
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    worker.result.update(outcome='not_needed', booking_clicks=0, successful_refills=0)
    assert runtime._run('refill', worker.report) == 0
    worker.state.authorize_first_refill.assert_called_once()
    worker.state.accept_refill.assert_not_called()
    assert worker.state.first_refill_authorized is True
    assert worker.report['automatic_enabled'] is False


def test_manual_successful_receipt_enables_automatic_runs(worker, monkeypatch):
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    assert runtime._run('refill', worker.report) == 0
    worker.state.accept_refill.assert_called_once()
    assert worker.report['automatic_enabled'] is True


def test_unknown_refill_never_enables_automatic_runs(worker, monkeypatch):
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    worker.result.update(outcome='unknown_after_click', successful_refills=0)
    assert runtime._run('refill', worker.report) == 2
    worker.state.accept_refill.assert_not_called()
    assert worker.report['automatic_enabled'] is False


def test_success_counter_without_provider_receipt_never_enables_automatic_runs(worker, monkeypatch):
    import aldi_live_refill_contract as contract
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    monkeypatch.setitem(contract._STATE, 'contract', SimpleNamespace(success=False))
    assert runtime._run('refill', worker.report) == 0
    worker.state.accept_refill.assert_not_called()
    assert worker.report['automatic_enabled'] is False


def test_main_report_never_echoes_unexpected_exception_text(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'report.json'
    monkeypatch.setenv('ALDI_HOSTED_REPORT', str(path))
    monkeypatch.setattr(runtime, '_run', Mock(side_effect=RuntimeError(PASSWORD + ACCOUNT)))
    assert runtime.main(['--mode', 'observe']) == 2
    text = path.read_text() + capsys.readouterr().out
    assert PASSWORD not in text and ACCOUNT not in text
    assert json.loads(path.read_text())['outcome'] == 'runtime_error'


@pytest.mark.parametrize('mode,error,outcome,exit_code', [
    ('automatic', http.LoginError('auth_backoff_active'), 'auth_backoff_active', 0),
    ('refill', http.LoginError('auth_backoff_active'), 'auth_backoff_active', 2),
    ('observe', http.LoginError('auth_backoff_active'), 'auth_backoff_active', 2),
    ('automatic', http.LoginError('provider_http_error'), 'provider_http_error', 2),
    ('refill', http.LoginError('provider_http_error'), 'provider_http_error', 2),
    ('automatic', runtime.HostedRuntimeError('legacy_state_unconfirmed'), 'legacy_state_unconfirmed', 2),
    ('automatic', RuntimeError('PRIVATE_ERROR'), 'runtime_error', 2),
    ('refill', RuntimeError('PRIVATE_ERROR'), 'runtime_error', 2),
])
def test_main_only_scheduled_auth_wait_is_a_nonfailing_outcome(
        tmp_path, monkeypatch, capsys, mode, error, outcome, exit_code):
    path = tmp_path / 'report.json'
    monkeypatch.setenv('ALDI_HOSTED_REPORT', str(path))
    def fail(mode, report):
        if isinstance(error, http.LoginError) and str(error) == 'auth_backoff_active':
            report['retry_after'] = '2026-10-26T22:48:21Z'
        raise error
    monkeypatch.setattr(runtime, '_run', fail)
    assert runtime.main(['--mode', mode]) == exit_code
    report = json.loads(path.read_text())
    assert report['outcome'] == outcome
    assert report['login_verified'] is False
    assert report['automatic_enabled'] is False
    assert report['credential_submissions'] == report['booking_clicks'] == 0
    assert 'PRIVATE_ERROR' not in path.read_text() + capsys.readouterr().out
    if outcome == 'auth_backoff_active':
        assert report['retry_after'] == '2026-10-26T22:48:21Z'
        assert 'Frühester neuer Passwort-Login' in runtime.render_summary(report)


@pytest.mark.parametrize('report', [None, '{PRIVATE_BROKEN', json.dumps({
    'outcome': 'auth_backoff_active', 'retry_after': '2026-10-26T22:48:21Z',
})])
def test_summary_cli_works_without_installed_dependencies(tmp_path, report):
    script = Path(runtime.__file__).resolve()
    if report is not None:
        (tmp_path / 'aldi-hosted-report.json').write_text(report)
    result = subprocess.run([sys.executable, '-S', str(script), '--summary-only'],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'PRIVATE_BROKEN' not in result.stdout
    if report is None or report == '{PRIVATE_BROKEN':
        assert 'Ergebnis nicht bestätigt' in result.stdout
        assert 'nicht blind erneut buchen' in result.stdout
    else:
        assert '2026-10-26 22:48:21 UTC' in result.stdout


def test_summary_never_echoes_arbitrary_fields():
    text = runtime.render_summary({'outcome': 'PRIVATE_OUTCOME',
                                   'retry_after': '<script>PRIVATE_TIME</script>',
                                   'password': PASSWORD, 'cookies': 'PRIVATE_COOKIE'})
    assert 'PRIVATE' not in text
