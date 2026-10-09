from unittest.mock import MagicMock, patch

import pytest

from core.aldi_booking import BookingUnknownError, execute_free_one_gb_selenium


ACCOUNT = '0152 00000000'
SELECTORS = {
    'account': '.account',
    'active_tariff': '.tariff',
    'refill_offer': '.offer',
    'refill_button': '.refill',
    'refill_success': '.success',
    'refill_reconcile': '.history-latest-refill',
}
ELIGIBLE = {
    'refill_eligible': True,
    'refill_type': 'FREE_ONE_GB',
    'refill_reason': 'free_one_gb_offer_available',
    'account_verified': True,
}


class ImmediateWait:
    def __init__(self, driver, timeout):
        self.driver = driver
        self.timeout = timeout

    def until(self, condition):
        value = condition(self.driver)
        if not value:
            raise TimeoutError('condition_not_met')
        return value


def test_unconfigured_selectors_block_without_click():
    driver = MagicMock()
    result = execute_free_one_gb_selenium(driver, ACCOUNT, {})
    assert result['booking_status'] == 'BLOCKED'
    assert result['booking_reason'] == 'selectors_unconfigured'
    driver.click.assert_not_called()


def test_unverified_reconciliation_blocks_before_click():
    driver = MagicMock()
    with patch('core.aldi_booking.inspect_selenium', return_value=ELIGIBLE), \
         patch('core.aldi_booking.reconciliation_snapshot', return_value=('UNKNOWN', None)), \
         patch('core.aldi_booking._unique') as unique:
        result = execute_free_one_gb_selenium(driver, ACCOUNT, SELECTORS)
    assert result['booking_status'] == 'BLOCKED'
    assert result['booking_reason'] == 'reconciliation_unverified'
    unique.assert_not_called()


def test_exactly_one_click_requires_changed_provider_reconciliation():
    driver = MagicMock()
    offer = MagicMock()
    button = MagicMock()
    button.is_enabled.return_value = True
    button.get_attribute.return_value = None

    def unique(_driver, selector, scope=None):
        if selector == '.offer':
            return offer
        if selector == '.refill' and scope is offer:
            return button
        raise AssertionError(selector)

    with patch('core.aldi_booking.inspect_selenium', side_effect=[ELIGIBLE, ELIGIBLE]), \
         patch('core.aldi_booking.reconciliation_snapshot', side_effect=[('NONE', None), ('SUCCESS', 'new-hash')]), \
         patch('core.aldi_booking.success_snapshot', return_value=('SUCCESS', 'confirm-hash')), \
         patch('core.aldi_booking._unique', side_effect=unique), \
         patch('core.aldi_booking.element_label', return_value='1 GB nachbuchen'), \
         patch('core.aldi_booking.protected_session_visible', return_value=True), \
         patch('selenium.webdriver.support.ui.WebDriverWait', ImmediateWait):
        result = execute_free_one_gb_selenium(driver, ACCOUNT, SELECTORS)

    assert result['booking_status'] == 'SUCCESS'
    assert result['booking_executed'] is True
    assert result['booking_reason'] == 'free_one_gb_reconciled'
    assert result['reconcile_fingerprint'] == 'new-hash'
    button.click.assert_called_once_with()
    driver.refresh.assert_called_once_with()


def test_unchanged_reconciliation_after_click_is_unknown_and_never_retried():
    driver = MagicMock()
    offer = MagicMock()
    button = MagicMock()
    button.is_enabled.return_value = True
    button.get_attribute.return_value = None

    def unique(_driver, selector, scope=None):
        if selector == '.offer':
            return offer
        if selector == '.refill' and scope is offer:
            return button
        raise AssertionError(selector)

    with patch('core.aldi_booking.inspect_selenium', side_effect=[ELIGIBLE, ELIGIBLE]), \
         patch('core.aldi_booking.reconciliation_snapshot', side_effect=[('SUCCESS', 'same-hash'), ('SUCCESS', 'same-hash')]), \
         patch('core.aldi_booking.success_snapshot', return_value=('SUCCESS', 'confirm-hash')), \
         patch('core.aldi_booking._unique', side_effect=unique), \
         patch('core.aldi_booking.element_label', return_value='1 GB nachbuchen'), \
         patch('core.aldi_booking.protected_session_visible', return_value=True), \
         patch('selenium.webdriver.support.ui.WebDriverWait', ImmediateWait):
        with pytest.raises(BookingUnknownError):
            execute_free_one_gb_selenium(
                driver, ACCOUNT, SELECTORS,
                baseline_reconcile_fingerprint='same-hash',
            )

    button.click.assert_called_once_with()
    driver.refresh.assert_called_once_with()
