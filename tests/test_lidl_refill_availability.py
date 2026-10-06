import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.database import Database
from core.lidl_refill import assess_refill, inspect_selenium
from plugins.lidl_connect import LidlConnectWatcher


OFFER = '1 GB Unlimited Nachbuchoption / Refill kostenlos 0,00 €'
ELIGIBLE = assess_refill('Unlimited on Demand S', OFFER, '1 GB nachbuchen', True)
SELECTORS = {'active_tariff': '.active', 'refill_offer': '.offer',
             'refill_button': '.refill', 'refill_success': '.new-success'}


@pytest.mark.parametrize('tariff,offer,button,enabled,expected', [
    ('Unlimited on Demand S', OFFER, '1 GB nachbuchen', True, True),
    ('LIDL Connect Unlimited on Demand L', OFFER, 'Buchen', True, True),
    ('SMART S', OFFER, 'Buchen', True, False),
    ('Unlimited on Demand S', '1 GB Speed-Bucket 2,99 €', 'Buchen', True, False),
    ('Unlimited on Demand S', OFFER + ' 1,99 €', 'Buchen', True, False),
    ('Unlimited on Demand S', OFFER.replace('1 GB', '2 GB'), 'Buchen', True, False),
    ('Unlimited on Demand S', OFFER.replace('1 GB', '1.000 GB'), 'Buchen', True, False),
    ('Unlimited on Demand S', '1 GB Unlimited Refill', 'Buchen', True, False),
    ('Unlimited on Demand S', OFFER, 'Buchen', False, False),
    ('Unlimited on Demand S', OFFER + ' nicht kostenlos', 'Buchen', True, False),
    ('Unlimited on Demand S', OFFER + ' automatische Verlängerung', 'Buchen', True, False),
    ('Unlimited on Demand S', OFFER, 'Tarif wechseln', True, False),
    ('SMART S und Unlimited on Demand S', OFFER, 'Buchen', True, False),
])
def test_specific_free_offer_only(tariff, offer, button, enabled, expected):
    assert assess_refill(tariff, offer, button, enabled)['refill_eligible'] is expected


def locator(text='', visible=True, enabled=True, count=1):
    element = MagicMock()
    element.count = AsyncMock(return_value=count)
    element.is_visible = AsyncMock(return_value=visible)
    element.is_enabled = AsyncMock(return_value=enabled)
    element.get_attribute = AsyncMock(return_value=None)
    element.inner_text = AsyncMock(return_value=text)
    element.click = AsyncMock()
    element.wait_for = AsyncMock()
    return element


def browser_watcher(tmp_path, **kwargs):
    db = Database(str(tmp_path / 'persistent.sqlite'))
    watcher = LidlConnectWatcher('fake', 'fake', 100, dry_run=False, use_api=False,
                                 database=db, refill_selectors=SELECTORS, **kwargs)
    page = MagicMock()
    page.url = 'https://kundenkonto.lidl-connect.de/mein-lidl-connect.html'
    page.close = AsyncMock()
    tariff, offer = locator('Unlimited on Demand S'), locator(OFFER)
    button = locator('1 GB nachbuchen')
    success = locator('1 GB erfolgreich nachgebucht', visible=False)
    offer.locator.return_value = button
    page.locator.side_effect = lambda selector: {
        '.active': tariff, '.offer': offer, '.new-success': success,
        "input[type='password']": locator(visible=False, count=0),
    }.get(selector, locator('Abmelden'))
    watcher.page = page
    return watcher, db, page, offer, button, success


def test_read_only_eligibility_does_not_click(tmp_path):
    watcher, _, _, _, button, _ = browser_watcher(tmp_path)
    assert asyncio.run(watcher._pw_refill_evidence()) == ELIGIBLE
    button.click.assert_not_awaited()


@pytest.mark.parametrize('kind', ['ambiguous', 'hidden', 'disabled', 'aria_disabled', 'paid', 'wrong_origin'])
def test_browser_rejects_unsafe_candidate(tmp_path, kind):
    watcher, _, page, offer, button, _ = browser_watcher(tmp_path)
    if kind == 'ambiguous':
        button.count.return_value = 2
    elif kind == 'hidden':
        button.is_visible.return_value = False
    elif kind == 'disabled':
        button.is_enabled.return_value = False
    elif kind == 'aria_disabled':
        button.get_attribute.return_value = 'true'
    elif kind == 'paid':
        offer.inner_text.return_value = OFFER + ' 2,99 €'
    else:
        page.url = 'https://attacker.invalid/'
    assert not asyncio.run(watcher._pw_refill_evidence())['refill_eligible']
    assert asyncio.run(watcher._pw_trigger_recharge()) is False
    button.click.assert_not_awaited()


def test_live_run_persists_pending_before_one_click_and_confirms(tmp_path):
    watcher, db, _, _, button, success = browser_watcher(tmp_path)
    watcher.check_usage = AsyncMock(return_value={'used_mb': 1, 'total_mb': 1000, **ELIGIBLE})
    async def click(**kwargs):
        assert len(db.get_unresolved_recharges()) == 1
        assert db.get_unresolved_recharges()[0].status == 'PENDING'
        success.is_visible.return_value = True
    button.click.side_effect = click
    result = asyncio.run(watcher.run())
    assert result.should_recharge and result.recharge_triggered
    assert result.recharge_status == 'SUCCESS'
    assert not db.get_unresolved_recharges()
    button.click.assert_awaited_once()
    assert asyncio.run(watcher.run()).recharge_status == 'BLOCKED'
    button.click.assert_awaited_once()


@pytest.mark.parametrize('notice', ['Erfolgreich', '2 GB erfolgreich gebucht', '1 GB nicht erfolgreich gebucht', '1 GB und 2 GB erfolgreich gebucht'])
def test_unspecific_confirmation_is_unknown_and_blocks_second_click(tmp_path, notice):
    watcher, db, _, _, button, success = browser_watcher(tmp_path)
    success.inner_text.return_value = notice
    watcher.check_usage = AsyncMock(return_value={'used_mb': 990, 'total_mb': 1000, **ELIGIBLE})
    first = asyncio.run(watcher.run())
    assert first.recharge_status == 'UNKNOWN'
    assert db.get_unresolved_recharges()[0].status == 'UNKNOWN'
    assert asyncio.run(watcher.run()).recharge_status == 'BLOCKED'
    button.click.assert_awaited_once()


def test_stale_success_notice_does_not_book(tmp_path):
    watcher, _, _, _, button, success = browser_watcher(tmp_path)
    success.is_visible.return_value = True
    assert not asyncio.run(watcher._pw_trigger_recharge())
    button.click.assert_not_awaited()


def test_direct_booking_cannot_bypass_dry_run_or_journal(tmp_path):
    watcher, db, _, _, button, _ = browser_watcher(tmp_path)
    assert not asyncio.run(watcher.trigger_recharge())
    assert not asyncio.run(watcher.trigger_recharge('invented'))
    pending = db.begin_recharge(watcher.provider_name, watcher.username)
    watcher.dry_run = True
    assert not asyncio.run(watcher.trigger_recharge(pending))
    button.click.assert_not_awaited()


def test_api_does_not_pick_first_data_tariff():
    watcher = LidlConnectWatcher('fake', 'fake', 100)
    watcher._get_api_session = AsyncMock()
    assert not asyncio.run(watcher._api_trigger_recharge())
    watcher._get_api_session.assert_not_awaited()


@pytest.mark.parametrize('used,total,expected', [(950, 1000, True), (800, 1000, False),
                                               (False, 1000, False), (float('nan'), 1000, False)])
def test_need_mode_uses_remaining_not_consumed(used, total, expected):
    watcher = LidlConnectWatcher('fake', 'fake', 100, refill_mode='needed')
    assert watcher.should_recharge_for_usage({'used_mb': used, 'total_mb': total, **ELIGIBLE}) is expected


def test_selenium_scopes_button_inside_offer_and_never_clicks():
    from selenium.webdriver.common.by import By
    driver = MagicMock()
    driver.current_url = 'https://kundenkonto.lidl-connect.de/'
    tariff, offer, button = MagicMock(), MagicMock(), MagicMock()
    tariff.text, offer.text, button.text = 'Unlimited on Demand S', OFFER, 'Buchen'
    button.get_attribute.return_value = None
    driver.find_elements.side_effect = lambda by, selector: [tariff] if selector == '.active' else [offer]
    offer.find_elements.return_value = [button]
    with patch('monitoring.session_visible', return_value=True):
        assert inspect_selenium(driver, SELECTORS) == ELIGIBLE
    offer.find_elements.assert_called_once_with(By.CSS_SELECTOR, '.refill')
    button.click.assert_not_called()


def test_unconfigured_selectors_do_not_inspect_or_book():
    driver = MagicMock()
    assert inspect_selenium(driver, {})['refill_reason'] == 'selectors_unconfigured'
    driver.find_elements.assert_not_called()


def test_dry_run_reports_available_refill_without_click(tmp_path):
    watcher, db, _, _, button, _ = browser_watcher(tmp_path)
    watcher.dry_run = True
    watcher.check_usage = AsyncMock(return_value={'used_mb': 1, 'total_mb': 1000, **ELIGIBLE})
    result = asyncio.run(watcher.run())
    assert result.should_recharge and not result.recharge_triggered
    button.click.assert_not_awaited()
    assert not db.get_unresolved_recharges()
