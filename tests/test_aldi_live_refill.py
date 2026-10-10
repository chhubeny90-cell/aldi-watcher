from unittest.mock import Mock
import json
from core.database import Database

import aldi_live_refill as live


def _eligible(control):
    return ({
        'refill_eligible': True,
        'refill_type': 'FREE_UNLIMITED',
        'refill_reason': 'free_one_gb_button_available',
        'refill_candidate_count': 1,
        'tariff_evidence': 'TARIF_S',
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
    monkeypatch.setattr(live, 'ALDI_RECONCILIATION_VERIFIED', True)
    monkeypatch.setattr(live.watcher, 'ALDI_ACCOUNT_USER', '01500000000')
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    monkeypatch.setattr(live, 'REPORT_PATH', str(tmp_path / 'report.json'))
    monkeypatch.setattr(live, 'CLICK_SETTLE_SECONDS', 0)
    monkeypatch.setattr(live.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(live.watcher, 'configure_credentials', lambda *_: True)
    monkeypatch.setattr(live.watcher, 'build_driver', lambda: driver)
    monkeypatch.setattr(live.watcher, 'aldi_login', lambda *_: True)

    remaining = iter(remaining_values)
    monkeypatch.setattr(live, '_safe_status', lambda *_: next(remaining))

    evidence = iter(evidence_values)
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


def test_exactly_one_gb_can_still_refill(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(
        monkeypatch,
        tmp_path,
        [1.0, 2.0],
        [_eligible(control), _unavailable('offer_unverified')],
    )
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')

    assert live.main() == 2
    click.assert_called_once_with(driver, control)


def test_paid_or_ambiguous_offer_never_clicks(monkeypatch, tmp_path):
    driver = _setup(monkeypatch, tmp_path, [0.4], [_unavailable()])

    assert live.main() == 0
    driver.execute_script.assert_not_called()


def test_volume_increase_does_not_prove_success(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(
        monkeypatch,
        tmp_path,
        [0.2, 1.2],
        [_eligible(control), _unavailable('offer_unverified')],
    )
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')

    assert live.main() == 2
    click.assert_called_once_with(driver, control)


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
        [0.0, 0.6, 1.4],
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


def test_unverified_provider_adapter_blocks_before_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv('AUTO_BOOK_ENABLED', 'true')
    monkeypatch.setattr(live, 'REPORT_PATH', str(tmp_path / 'report.json'))
    configure = Mock(side_effect=AssertionError('no login'))
    monkeypatch.setattr(live.watcher, 'configure_credentials', configure)
    assert live.main() == 3
    configure.assert_not_called()


def test_pending_is_committed_before_click_and_unknown_survives_next_run(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2, 1.2], [_eligible(control), _unavailable()])
    db = Database(str(tmp_path / 'journal.sqlite'))
    ids = []

    def click(*_):
        records = db.get_unresolved_recharges('alditalk', '01500000000')
        assert len(records) == 1 and records[0].status == 'PENDING'
        ids.append(records[0].recharge_id)
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'book')
    assert live.main() == 2
    assert db.get_unresolved_recharges()[0].status == 'UNKNOWN'
    build = Mock(side_effect=AssertionError('unresolved must block before login'))
    monkeypatch.setattr(live.watcher, 'build_driver', build)
    assert live.main() == 2
    build.assert_not_called()
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
        }))
        stack.enter_context(patch.object(live, 'ALDI_RECONCILIATION_VERIFIED', True))
        stack.enter_context(patch.object(live, 'REPORT_PATH', db_path + '.' + str(os.getpid()) + '.json'))
        stack.enter_context(patch.object(live.watcher, 'ALDI_ACCOUNT_USER', '01500000000'))
        stack.enter_context(patch.object(live.watcher, 'configure_credentials', return_value=True))
        stack.enter_context(patch.object(live.watcher, 'build_driver', return_value=driver))
        stack.enter_context(patch.object(live.watcher, 'aldi_login', return_value=True))
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
        looked_up.append(recharge_id)
        return 'SUCCESS' if recharge_id in calls.read_text().splitlines() else 'UNKNOWN'
    monkeypatch.setattr(live, 'check_recharge_status', receipt_lookup)
    build = Mock(side_effect=AssertionError('recovery must not issue a booking'))
    monkeypatch.setattr(live.watcher, 'build_driver', build)
    assert live.main() == 2  # recovery-only run, no fresh booking
    assert looked_up == [pending.recharge_id]
    assert db.get_unresolved_recharges() == []
    assert db.set_recharge_status(pending.recharge_id, 'UNKNOWN') == 'SUCCESS'
    assert calls.read_text().splitlines() == [pending.recharge_id]
    build.assert_not_called()


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
