from unittest.mock import Mock, call

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


def test_paid_or_ambiguous_offer_never_clicks(monkeypatch, tmp_path):
    driver = _setup(monkeypatch, tmp_path, [0.4], [_unavailable()])

    assert live.main() == 0
    driver.execute_script.assert_not_called()


def test_one_free_refill_is_clicked_once_and_verified(monkeypatch, tmp_path):
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

    assert live.main() == 0
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


def test_two_verified_free_refills_are_allowed_when_portal_reoffers(monkeypatch, tmp_path):
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

    assert live.main() == 0
    assert click.call_args_list == [call(driver, first), call(driver, second)]


def test_unverified_control_kind_is_not_clicked(monkeypatch, tmp_path):
    control = Mock()
    driver = _setup(monkeypatch, tmp_path, [0.2], [_eligible(control)])
    click = Mock()
    monkeypatch.setattr(live, '_trusted_click', click)
    monkeypatch.setattr(live, '_action_kind', lambda *_: 'unknown')

    assert live.main() == 2
    click.assert_not_called()
