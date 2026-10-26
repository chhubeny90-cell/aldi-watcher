from unittest.mock import Mock
import json
import pytest
from core.database import Database, RechargeLockedError

import aldi_live_refill as live


def _eligible(control):
    return ({
        'refill_eligible': True,
        'refill_type': 'FREE_UNLIMITED',
        'refill_reason': 'free_one_gb_button_available',
        'refill_candidate_count': 1,
        'tariff_evidence': 'TARIF_S',
        'free_evidence': 'explicit_free_offer',
    }, control)


def _unavailable(reason='price_unverified_or_paid'):
    return ({
        'refill_eligible': False,
        'refill_type': 'UNKNOWN',
        'refill_reason': reason,
        'refill_candidate_count': 0,
    }, None)


def _setup(monkeypatch, tmp_path, remaining_values, evidence_values):
    driver = Mock()
    # Unit tests simulate a durable local host, independently of the CI host.
    # The separate hosted-runner regression explicitly tests that rejection.
    monkeypatch.setenv('GITHUB_ACTIONS', 'false')
    db_path = tmp_path / 'journal.sqlite'
    Database(str(db_path))
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(db_path))
    monkeypatch.setattr(live.watcher, 'ALDI_ACCOUNT_USER', '01500000000')
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    monkeypatch.setenv('ALDI_EXPECTED_ACCOUNT', '01500000000')
    monkeypatch.setenv('ALDI_REQUIRED_TARGET_SUFFIX', '0000')
    monkeypatch.setattr(live, 'REPORT_PATH', str(tmp_path / 'report.json'))
    monkeypatch.setattr(live, 'CLICK_SETTLE_SECONDS', 0)
    monkeypatch.setattr(live.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(live.watcher, 'configure_credentials', lambda *_: True)
    monkeypatch.setattr(live.watcher, 'build_driver', lambda: driver)
    monkeypatch.setattr(live.watcher, 'aldi_login', lambda *_: True)
    monkeypatch.setattr(live, 'verify_account_selenium', lambda *_: 'a' * 64)
    monkeypatch.setattr(live, 'tariff_identity_selenium', lambda *_: 'b' * 64)

    remaining = iter(remaining_values)
    monkeypatch.setattr(live, '_safe_status', lambda *_: next(remaining))

    # Each cycle reads the priced offer, revalidates it before clicking, then
    # optionally checks a confirmation step. The fixture retains the same offer
    # until the simulated first click; tests can override this for actual changes.
    observed = []
    for index, value in enumerate(evidence_values):
        observed.append(value)
        if index % 2 == 0 and value[0].get('refill_eligible'):
            observed.append(value)
    evidence = iter(observed)
    monkeypatch.setattr(live, 'locate_selenium', lambda *_: next(evidence))
    return driver


def test_booking_disabled_never_builds_browser(monkeypatch, tmp_path):
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'false')
    monkeypatch.setattr(live, 'REPORT_PATH', str(tmp_path / 'report.json'))
    build = Mock(side_effect=AssertionError('browser must not start'))
    monkeypatch.setattr(live.watcher, 'build_driver', build)

    assert live.main() == 3
    build.assert_not_called()


def test_volume_above_threshold_never_clicks(monkeypatch, tmp_path):
    driver = _setup(monkeypatch, tmp_path, [1.001], [])

    assert live.main() == 0
    driver.execute_script.assert_not_called()


def test_exactly_one_gb_is_not_eligible_for_free_refill(monkeypatch, tmp_path):
    driver = _setup(monkeypatch, tmp_path, [1.0], [])
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)

    assert live.main() == 0
    click.assert_not_called()
    driver.execute_script.assert_not_called()


def test_paid_or_ambiguous_offer_never_clicks(monkeypatch, tmp_path):
    driver = _setup(monkeypatch, tmp_path, [0.4], [_unavailable()])

    assert live.main() == 0
    driver.execute_script.assert_not_called()


@pytest.mark.parametrize('stage', ['initial', 'recheck'])
@pytest.mark.parametrize('free_evidence', [None, 'official_unlimited_entitlement', 'unverified'])
def test_live_booking_requires_explicit_free_price_at_each_offer_read(
        monkeypatch, tmp_path, stage, free_evidence):
    control = Mock()
    _setup(monkeypatch, tmp_path, [0.2], [])
    evidence, _ = _eligible(control)
    if free_evidence is None:
        evidence.pop('free_evidence')
    else:
        evidence['free_evidence'] = free_evidence
    offers = [(evidence, control)]
    if stage == 'recheck':
        offers.insert(0, _eligible(control))
    monkeypatch.setattr(live, 'locate_selenium', Mock(side_effect=offers))
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)

    assert live.main() == 2
    click.assert_not_called()
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['outcome'] == 'zero_price_unverified'
    assert report['booking_clicks'] == 0
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges() == []


@pytest.mark.parametrize('eligible', ['true', 1])
def test_truthy_eligibility_is_not_a_verified_offer(monkeypatch, tmp_path, eligible):
    control = Mock()
    evidence, _ = _eligible(control)
    evidence['refill_eligible'] = eligible
    _setup(monkeypatch, tmp_path, [0.2], [(evidence, control)])
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)

    assert live.main() == 0
    click.assert_not_called()
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges() == []


@pytest.mark.parametrize('after', [0.2, 0.8, 1.2, 2.2])
def test_refreshed_volume_without_official_receipt_stays_unknown(monkeypatch, tmp_path, after):
    control = Mock()
    driver = _setup(
        monkeypatch,
        tmp_path,
        [0.2, after],
        [_eligible(control), _unavailable('offer_unverified')],
    )
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')

    assert live.ALDI_RECONCILIATION_VERIFIED is False
    history = Mock(side_effect=AssertionError('No receipt lookup exists for this new operation'))
    monkeypatch.setattr(live, 'check_recharge_status', history)
    assert live.main() == 2
    click.assert_called_once_with(driver, control)
    history.assert_not_called()
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['outcome'] == 'unknown_after_click'
    assert report['successful_refills'] == 0
    cycle = report['cycles'][0]
    assert cycle['recharge_status'] == 'UNKNOWN'
    assert cycle['verified'] is False
    assert cycle['confirmation'] == 'unverified'
    assert cycle['observed_volume_delta_gb'] == pytest.approx(after - 0.2)
    assert cycle['identity_unchanged'] is True
    records = Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges()
    assert len(records) == 1 and records[0].status == 'UNKNOWN'
    assert records[0].recharge_id == cycle['recharge_id']


def test_unverified_result_after_click_never_repeats_booking(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(
        monkeypatch,
        tmp_path,
        [0.2, 0.2],
        [_eligible(control), _unavailable('offer_unverified')],
    )
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')

    assert live.main() == 2
    click.assert_called_once_with(driver, control)


def test_reoffered_control_cannot_bypass_unknown(monkeypatch, tmp_path):
    first = Mock()
    second = Mock()
    driver = _setup(
        monkeypatch,
        tmp_path,
        [0.0, 0.0, 1.4],
        [
            _eligible(first), _unavailable('offer_unverified'),
            _eligible(second), _unavailable('offer_unverified'),
        ],
    )
    monkeypatch.setattr(live, 'MAX_REFILLS_PER_RUN', 2)
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')

    assert live.main() == 2
    click.assert_called_once_with(driver, first)


def test_positive_volume_below_threshold_cannot_trigger_second_refill_or_restart_retry(monkeypatch, tmp_path):
    first, second = Mock(), Mock()
    driver = _setup(
        monkeypatch,
        tmp_path,
        [0.2, 0.8, 1.2],
        [
            _eligible(first), _unavailable(),
            _eligible(second), _unavailable(),
        ],
    )
    monkeypatch.setattr(live, 'MAX_REFILLS_PER_RUN', 2)
    clicks = []
    monkeypatch.setattr(live, '_trusted_click', lambda session, control: clicks.append((session, control)))
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')

    assert live.main() == 2
    assert clicks == [(driver, first)]
    report = json.loads((tmp_path / 'report.json').read_text())
    assert len(report['cycles']) == 1
    assert report['successful_refills'] == 0
    db = Database(str(tmp_path / 'journal.sqlite'))
    records = db.get_unresolved_recharges()
    assert len(records) == 1 and records[0].status == 'UNKNOWN'
    recharge_id = records[0].recharge_id

    # The GitHub adapter must not release this guard using its stored baseline.
    import github_live_refill as hosted
    monkeypatch.setattr(live, 'check_recharge_status', hosted._recover_recharge_status)
    # A separate run must recover the same unresolved operation without clicking.
    for _ in range(3):
        assert live.main() == 2
        assert clicks == [(driver, first)]
        records = db.get_unresolved_recharges()
        assert len(records) == 1
        assert records[0].recharge_id == recharge_id
        assert records[0].status == 'UNKNOWN'


@pytest.mark.parametrize('fail_all_updates', [False, True])
def test_journal_update_failure_preserves_prior_outcome_and_durable_guard(
        monkeypatch, tmp_path, fail_all_updates):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    original = Database.set_recharge_status
    updates = []

    def failing_update(db, recharge_id, status, *args, **kwargs):
        updates.append(recharge_id)
        if fail_all_updates or len(updates) == 2:
            raise OSError('private journal details must not enter reports')
        return original(db, recharge_id, status, *args, **kwargs)

    monkeypatch.setattr(Database, 'set_recharge_status', failing_update)
    assert live.main() == 2
    click.assert_called_once_with(driver, control)
    driver.quit.assert_called_once()
    report_text = (tmp_path / 'report.json').read_text()
    report = json.loads(report_text)
    assert report['outcome'] == 'journal_update_failed'
    assert report['outcome_before_journal_failure'] == (
        'error' if fail_all_updates else 'unknown_after_click')
    assert report['journal_exception_type'] == 'OSError'
    assert report['successful_refills'] == 0
    assert report['finished_at'] is not None
    assert 'private journal details' not in report_text
    db = Database(str(tmp_path / 'journal.sqlite'))
    records = db.get_unresolved_recharges()
    assert len(records) == 1
    assert records[0].recharge_id == report['cycles'][0]['recharge_id']
    assert records[0].status == ('PENDING' if fail_all_updates else 'UNKNOWN')
    with pytest.raises(RechargeLockedError):
        db.begin_recharge('alditalk', '01500000000')


def test_visible_plus_one_gb_button_is_recognized_after_offer_gate(monkeypatch):
    monkeypatch.setattr(live, 'element_label', lambda *_: '+1 GB')
    assert live._action_kind(object(), object()) == 'book'


def test_unverified_control_kind_is_not_clicked(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2], [_eligible(control)])
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'unknown')

    assert live.main() == 2
    click.assert_not_called()


def test_unverified_current_account_blocks_before_booking(monkeypatch, tmp_path):
    control = Mock()
    _setup(monkeypatch, tmp_path, [0.2], [_eligible(control)])
    monkeypatch.setattr(live, 'verify_account_selenium', Mock(side_effect=RuntimeError('account_mismatch')))
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    assert live.main() == 2
    click.assert_not_called()
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges() == []


def test_pending_is_committed_before_click_and_unknown_survives_next_run(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 0.2], [_eligible(control), _unavailable()])
    db = Database(str(tmp_path / 'journal.sqlite'))
    ids = []
    recovery_sessions = []

    def click(*_):
        records = db.get_unresolved_recharges('alditalk', '01500000000')
        assert len(records) == 1 and records[0].status == 'PENDING'
        ids.append(records[0].recharge_id)

    def status_lookup(session, recharge_id):
        recovery_sessions.append(session)
        return 'UNKNOWN'

    monkeypatch.setattr(live, 'check_recharge_status', status_lookup)
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    assert live.main() == 2
    assert db.get_unresolved_recharges()[0].status == 'UNKNOWN'
    build = Mock(return_value=driver)
    monkeypatch.setattr(live.watcher, 'build_driver', build)
    assert live.main() == 2
    build.assert_called_once()
    assert recovery_sessions == [driver]
    assert len(ids) == 1
    assert db.get_unresolved_recharges()[0].recharge_id == ids[0]


def test_lost_or_unconfigured_journal_is_not_created(monkeypatch, tmp_path):
    import pytest
    monkeypatch.delenv('ALDI_JOURNAL_PATH', raising=False)
    with pytest.raises(RuntimeError, match='unavailable'):
        live.open_live_journal()
    missing = tmp_path / 'lost.sqlite'
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(missing))
    with pytest.raises(RuntimeError, match='unavailable'):
        live.open_live_journal()
    assert not missing.exists()


def test_hosted_runner_cannot_claim_durable_journal(monkeypatch, tmp_path):
    import pytest
    path = tmp_path / 'journal.sqlite'
    Database(str(path))
    monkeypatch.setenv('ALDI_JOURNAL_PATH', str(path))
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setenv('GITHUB_WORKSPACE', str(tmp_path / 'checkout'))
    monkeypatch.setenv('RUNNER_ENVIRONMENT', 'github-hosted')
    with pytest.raises(RuntimeError, match='durable_runner'):
        live.open_live_journal()


def _live_crash_worker(db_path, calls_path, before_click=False, crash=True, start=None):
    import os
    from unittest.mock import patch
    from contextlib import ExitStack
    from pathlib import Path
    driver, control = Mock(), Mock()
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            'AUTO_BOOK_ENABLED': 'true', 'ALDI_JOURNAL_PATH': db_path,
            'GITHUB_ACTIONS': 'false',
            'ALDI_EXPECTED_ACCOUNT': '01500000000',
            'ALDI_REQUIRED_TARGET_SUFFIX': '0000',
        }))
        stack.enter_context(patch.object(live, 'REPORT_PATH', db_path + '.' + str(os.getpid()) + '.json'))
        stack.enter_context(patch.object(live.watcher, 'ALDI_ACCOUNT_USER', '01500000000'))
        stack.enter_context(patch.object(live.watcher, 'configure_credentials', return_value=True))
        stack.enter_context(patch.object(live.watcher, 'build_driver', return_value=driver))
        stack.enter_context(patch.object(live.watcher, 'aldi_login', return_value=True))
        stack.enter_context(patch.object(live, 'verify_account_selenium', return_value='a' * 64))
        stack.enter_context(patch.object(live, 'tariff_identity_selenium', return_value='b' * 64))
        stack.enter_context(patch.object(live, '_safe_status', return_value=0.2))
        stack.enter_context(patch.object(live, 'locate_selenium', return_value=_eligible(control)))
        stack.enter_context(patch.object(live, '_action_kind', return_value='book'))
        if before_click:
            original = Database.begin_recharge
            def reserve(db, *args, **kwargs):
                original(db, *args, **kwargs)
                os._exit(24)
            stack.enter_context(patch.object(Database, 'begin_recharge', reserve))
        def provider_click(*_):
            record = Database(db_path).get_unresolved_recharges()[0]
            assert record.status == 'PENDING'
            with Path(calls_path).open('a') as stream:
                stream.write(record.recharge_id + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            if crash:
                os._exit(23)
        stack.enter_context(patch.object(live, '_trusted_click', provider_click))
        if start is not None:
            assert start.wait(10)
        live.main()


def test_live_crash_after_request_recovers_success_with_same_id_and_one_call(monkeypatch, tmp_path):
    import multiprocessing as mp
    db_path = str(tmp_path / 'journal.sqlite')
    calls = tmp_path / 'provider-receipts.txt'
    db = Database(db_path)
    process = mp.get_context('spawn').Process(target=_live_crash_worker, args=(db_path, str(calls)))
    process.start()
    process.join(15)
    assert process.exitcode == 23
    pending = db.get_unresolved_recharges()[0]
    assert pending.status == 'PENDING'
    assert calls.read_text().splitlines() == [pending.recharge_id]
    _setup(monkeypatch, tmp_path, [], [])
    looked_up = []
    def receipt_lookup(driver, recharge_id):
        assert driver is not None
        looked_up.append(recharge_id)
        return 'SUCCESS' if recharge_id in calls.read_text().splitlines() else 'UNKNOWN'
    monkeypatch.setattr(live, 'check_recharge_status', receipt_lookup)
    driver = Mock()
    build = Mock(return_value=driver)
    monkeypatch.setattr(live.watcher, 'build_driver', build)
    assert live.main() == 0  # recovery-only run, no fresh booking
    assert looked_up == [pending.recharge_id]
    assert db.get_unresolved_recharges() == []
    assert db.set_recharge_status(pending.recharge_id, 'UNKNOWN') == 'SUCCESS'
    assert calls.read_text().splitlines() == [pending.recharge_id]
    build.assert_called_once()


def test_live_crash_before_click_recovers_unknown_without_booking(monkeypatch, tmp_path):
    import multiprocessing as mp
    db_path = str(tmp_path / 'journal.sqlite')
    calls = tmp_path / 'provider-receipts.txt'
    db = Database(db_path)
    process = mp.get_context('spawn').Process(target=_live_crash_worker, args=(db_path, str(calls), True))
    process.start()
    process.join(15)
    assert process.exitcode == 24
    assert db.get_unresolved_recharges()[0].status == 'PENDING'
    assert not calls.exists()
    _setup(monkeypatch, tmp_path, [], [])
    assert live.main() == 2
    assert db.get_unresolved_recharges()[0].status == 'UNKNOWN'
    assert not calls.exists()


def test_live_four_processes_share_one_journal_and_issue_one_request(tmp_path):
    import multiprocessing as mp
    db_path = str(tmp_path / 'journal.sqlite')
    calls = tmp_path / 'provider-receipts.txt'
    Database(db_path)
    ctx = mp.get_context('spawn')
    start = ctx.Event()
    workers = [ctx.Process(target=_live_crash_worker,
        args=(db_path, str(calls), False, False, start)) for _ in range(4)]
    for process in workers:
        process.start()
    start.set()
    for process in workers:
        process.join(15)
        assert process.exitcode == 0
    records = Database(db_path).get_unresolved_recharges()
    assert len(records) == 1 and records[0].status == 'UNKNOWN'
    assert calls.read_text().splitlines() == [records[0].recharge_id]


def test_account_change_during_first_volume_refresh_never_clicks(monkeypatch, tmp_path):
    control = Mock()
    _setup(monkeypatch, tmp_path, [0.2], [_eligible(control)])
    monkeypatch.setattr(live, 'verify_account_selenium', Mock(side_effect=['a' * 64, 'c' * 64]))
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    assert live.main() == 2
    click.assert_not_called()
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges() == []


def test_account_change_before_click_never_reserves_or_books(monkeypatch, tmp_path):
    control = Mock()
    _setup(monkeypatch, tmp_path, [0.2], [_eligible(control)])
    monkeypatch.setattr(live, 'verify_account_selenium', Mock(side_effect=['a' * 64, 'a' * 64, 'c' * 64]))
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    assert live.main() == 2
    click.assert_not_called()
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges() == []


def test_offer_price_change_before_click_never_reserves_or_books(monkeypatch, tmp_path):
    control = Mock()
    _setup(monkeypatch, tmp_path, [0.2], [])
    monkeypatch.setattr(live, 'locate_selenium', Mock(side_effect=[_eligible(control), _unavailable()]))
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    assert live.main() == 2
    click.assert_not_called()
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges() == []


@pytest.mark.parametrize('changed', ['subscriptions', 'tariff'])
def test_positive_volume_from_changed_identity_is_unknown_without_second_click(monkeypatch, tmp_path, changed):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    if changed == 'subscriptions':
        monkeypatch.setattr(live, 'verify_account_selenium', Mock(side_effect=['a' * 64] * 4 + ['c' * 64]))
    else:
        monkeypatch.setattr(live, 'tariff_identity_selenium', Mock(side_effect=['b' * 64] * 3 + ['d' * 64]))
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    assert live.main() == 2
    click.assert_called_once_with(driver, control)
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges()[0].status == 'UNKNOWN'


def test_increase_larger_than_one_gb_cannot_confirm_this_one_gb_action(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 2.2], [_eligible(control), _unavailable()])
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    assert live.main() == 2
    click.assert_called_once_with(driver, control)
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges()[0].status == 'UNKNOWN'


@pytest.mark.parametrize('where', ['click', 'refresh'])
def test_timeout_keeps_one_durable_unknown_request_and_never_retries(monkeypatch, tmp_path, where):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    click = Mock(side_effect=TimeoutError('private driver data') if where == 'click' else None)
    if where == 'refresh':
        monkeypatch.setattr(live, '_safe_status', Mock(side_effect=[0.2, TimeoutError('private account data')]))
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    assert live.main() == 2
    click.assert_called_once_with(driver, control)
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges()[0].status == 'UNKNOWN'
    assert 'private' not in (tmp_path / 'report.json').read_text()


def test_old_unknown_is_not_reconciled_by_current_positive_volume_or_new_offer(monkeypatch, tmp_path):
    control = Mock()
    _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    db = Database(str(tmp_path / 'journal.sqlite'))
    old_id = db.begin_recharge('alditalk', '01500000000')
    db.set_recharge_status(old_id, 'UNKNOWN')
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_safe_status', Mock(side_effect=AssertionError('old UNKNOWN has no new baseline')))
    assert live.main() == 2
    click.assert_not_called()
    unresolved = db.get_unresolved_recharges()
    assert len(unresolved) == 1
    assert unresolved[0].recharge_id == old_id and unresolved[0].status == 'UNKNOWN'


def test_confirmation_is_repriced_after_awaited_account_check(monkeypatch, tmp_path):
    book, confirm = Mock(), Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 0.2], [])
    monkeypatch.setattr(live, 'locate_selenium', Mock(side_effect=[
        _eligible(book), _eligible(book), _eligible(confirm), _unavailable(),
    ]))
    monkeypatch.setattr(live, '_action_kind', lambda _, control: 'book' if control is book else 'confirm')
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    assert live.main() == 2
    click.assert_called_once_with(driver, book)
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['confirmation_clicks'] == 0
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges()[0].status == 'UNKNOWN'


@pytest.mark.parametrize('stage', ['initial', 'recheck'])
@pytest.mark.parametrize('free_evidence', [None, 'official_unlimited_entitlement'])
def test_confirmation_losing_explicit_free_price_is_never_clicked(
        monkeypatch, tmp_path, stage, free_evidence):
    book, confirm = Mock(), Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2], [])
    evidence, _ = _eligible(confirm)
    if free_evidence is None:
        evidence.pop('free_evidence')
    else:
        evidence['free_evidence'] = free_evidence
    confirmations = [(evidence, confirm)]
    if stage == 'recheck':
        confirmations.insert(0, _eligible(confirm))
    monkeypatch.setattr(live, 'locate_selenium', Mock(side_effect=[
        _eligible(book), _eligible(book), *confirmations,
    ]))
    monkeypatch.setattr(live, '_action_kind', lambda _, control: 'book' if control is book else 'confirm')
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)

    assert live.main() == 2
    click.assert_called_once_with(driver, book)
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['outcome'] == 'zero_price_unverified'
    assert report['confirmation_clicks'] == 0
    assert report['successful_refills'] == 0
    assert Database(str(tmp_path / 'journal.sqlite')).get_unresolved_recharges()[0].status == 'UNKNOWN'


def test_confirmation_with_fresh_explicit_free_price_can_be_clicked(monkeypatch, tmp_path):
    book, confirm = Mock(), Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 1.2], [])
    monkeypatch.setattr(live, 'locate_selenium', Mock(side_effect=[
        _eligible(book), _eligible(book), _eligible(confirm), _eligible(confirm),
    ]))
    monkeypatch.setattr(live, '_action_kind', lambda _, control: 'book' if control is book else 'confirm')
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)

    assert live.main() == 2  # A verified price does not replace the provider receipt.
    assert click.call_args_list == [((driver, book),), ((driver, confirm),)]
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['confirmation_clicks'] == 1
    assert report['outcome'] == 'unknown_after_click'


@pytest.mark.parametrize(('provider', 'username', 'outcome'), [
    ('aldi', '+49 150 0000000', 'unresolved_recharge_blocked'),
    ('ALDI_TALK', '01500000000', 'unresolved_recharge_blocked'),
    ('aldi-talk', '01500000000', 'unresolved_recharge_blocked'),
    ('alditalk', 'sim-private-alias', 'unresolved_account_mapping_required'),
    ('unmapped-provider', '01500000000', 'unresolved_account_mapping_required'),
    ('alditalk', '01500000001', 'unresolved_account_mapping_required'),
])
def test_legacy_alias_or_unmapped_unknown_cannot_be_hidden_by_new_account_key(
        monkeypatch, tmp_path, provider, username, outcome):
    control = Mock()
    _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    db = Database(str(tmp_path / 'journal.sqlite'))
    old_id = db.begin_recharge(provider, username)
    db.set_recharge_status(old_id, 'UNKNOWN')
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    assert live.main() == 2
    click.assert_not_called()
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['outcome'] == outcome
    records = db.get_unresolved_recharges()
    assert len(records) == 1 and records[0].recharge_id == old_id
    assert records[0].status == 'UNKNOWN'


def test_known_lidl_unknown_does_not_block_independent_aldi_refill(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    db = Database(str(tmp_path / 'journal.sqlite'))
    old_id = db.begin_recharge('lidlconnect', 'private-lidl-account')
    db.set_recharge_status(old_id, 'UNKNOWN')
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    assert live.main() == 2
    click.assert_called_once_with(driver, control)
    remaining = db.get_unresolved_recharges()
    assert len(remaining) == 2
    assert next(record for record in remaining if record.recharge_id == old_id).status == 'UNKNOWN'
    aldi = [record for record in remaining if record.provider == 'alditalk']
    assert len(aldi) == 1 and aldi[0].status == 'UNKNOWN'


def test_journal_wide_aldi_executor_lock_blocks_before_browser_start(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, [0.2, 1.2], [])
    db = Database(str(tmp_path / 'journal.sqlite'))
    build = Mock(side_effect=AssertionError('an alias worker already holds this journal executor'))
    monkeypatch.setattr(live.watcher, 'build_driver', build)
    with db.account_lock('alditalk_executor', 'all'):
        assert live.main() == 2
    build.assert_not_called()
    assert json.loads((tmp_path / 'report.json').read_text())['outcome'] == 'recharge_locked'
