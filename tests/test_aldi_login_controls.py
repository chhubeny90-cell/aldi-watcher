from unittest.mock import Mock, call
import pytest
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.keys import Keys
import watcher
from browser_dom import trusted_pointer_click


@pytest.fixture
def login_page(monkeypatch):
    driver = Mock(current_url=watcher.ALDI_LOGIN_URL)
    driver.execute_script.return_value = {'x': 10, 'y': 20, 'w': 100, 'h': 40, 'vw': 1400, 'vh': 1000}
    user, password, submit = (Mock() for _ in range(3))
    navigate_mock = Mock()
    for control in (user, password, submit):
        control.is_enabled.return_value = True
        control.get_attribute.return_value = None
    monkeypatch.setattr(watcher, 'ALDI_USER', 'PRIVATE_USER')
    monkeypatch.setattr(watcher, 'ALDI_PASS', 'PRIVATE_PASSWORD')
    monkeypatch.setattr(watcher, 'navigate', navigate_mock)
    monkeypatch.setattr(watcher, 'dismiss_cookie_banner', lambda *_: None)
    monkeypatch.setattr(watcher, 'element_label', lambda *_: 'Anmelden')
    monkeypatch.setattr(watcher, 'session_visible', lambda *_: True)
    monkeypatch.setattr(watcher, 'WAIT_TIMEOUT', .01)

    def elements(_, selector):
        if 'autocomplete' in selector:
            return [user]
        if 'password' in selector:
            return [password]
        return [submit]

    monkeypatch.setattr(watcher, 'find_visible_elements', elements)
    return driver, user, password, submit, navigate_mock


def assert_native_login_once(driver, submit):
    assert [item.args[1]['type'] for item in driver.execute_cdp_cmd.call_args_list] == [
        'mouseMoved', 'mousePressed', 'mouseReleased',
    ]
    assert all(item.args[0] == 'Input.dispatchMouseEvent' for item in driver.execute_cdp_cmd.call_args_list)
    assert all('.click(' not in item.args[0] for item in driver.execute_script.call_args_list)
    submit.click.assert_not_called()
    submit.send_keys.assert_not_called()


def test_shadow_controls_are_filled_blurred_and_submitted_once(login_page):
    driver, user, password, submit, navigate_mock = login_page
    assert watcher.aldi_login(driver)
    assert user.send_keys.call_args_list == [
        call(Keys.CONTROL, 'a'),
        call(Keys.BACKSPACE),
        call('PRIVATE_USER'),
        call(Keys.TAB),
    ]
    assert password.send_keys.call_args_list == [
        call(Keys.CONTROL, 'a'),
        call(Keys.BACKSPACE),
        call('PRIVATE_PASSWORD'),
        call(Keys.TAB),
    ]
    submit.click.assert_not_called()
    submit.send_keys.assert_not_called()
    assert_native_login_once(driver, submit)
    navigate_mock.assert_called_once_with(driver, watcher.ALDI_LOGIN_URL)


def test_untrusted_origin_never_receives_credentials(login_page):
    driver, user, password, submit, _ = login_page
    driver.current_url = 'https://attacker.invalid/'
    with pytest.raises(PermissionError):
        watcher.aldi_login(driver)
    user.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()
    submit.send_keys.assert_not_called()
    driver.execute_script.assert_not_called()


def test_sso_host_is_not_a_confirmed_portal_session(login_page):
    driver, user, password, submit, navigate_mock = login_page
    driver.current_url = 'https://login.alditalk-kundenbetreuung.de/signin/XUI/'
    with pytest.raises(TimeoutException):
        watcher.aldi_login(driver)
    assert_native_login_once(driver, submit)
    assert navigate_mock.call_args_list == [
        call(driver, watcher.ALDI_LOGIN_URL),
        call(driver, watcher.ALDI_OVERVIEW_URL, attempts=1),
    ]


def test_sso_session_can_be_confirmed_by_one_protected_page_probe(login_page):
    driver, user, password, submit, navigate_mock = login_page
    driver.current_url = 'https://login.alditalk-kundenbetreuung.de/signin/XUI/'

    def navigate_side_effect(_driver, url, attempts=2):
        if navigate_mock.call_count == 2:
            driver.current_url = watcher.ALDI_OVERVIEW_URL

    navigate_mock.side_effect = navigate_side_effect

    assert watcher.aldi_login(driver)
    assert_native_login_once(driver, submit)
    assert navigate_mock.call_args_list == [
        call(driver, watcher.ALDI_LOGIN_URL),
        call(driver, watcher.ALDI_OVERVIEW_URL, attempts=1),
    ]


def test_protected_content_can_confirm_session_without_visible_logout(monkeypatch):
    driver = Mock(current_url=watcher.ALDI_OVERVIEW_URL)
    driver.get_cookies.return_value = [{'name': 'session', 'value': 'PRIVATE'}]
    monkeypatch.setattr(watcher, 'session_visible', lambda *_: False)
    monkeypatch.setattr(watcher, 'find_visible_elements', lambda *_: [])
    monkeypatch.setattr(
        watcher,
        'rendered_text',
        lambda *_: 'Guthaben 10,00 € Datenvolumen verbleibend 0,8 GB Inland',
    )

    assert watcher.aldi_session_visible(driver) is True


def test_protected_content_fallback_rejects_login_form(monkeypatch):
    driver = Mock(current_url=watcher.ALDI_OVERVIEW_URL)
    password = Mock()
    driver.get_cookies.return_value = [{'name': 'session', 'value': 'PRIVATE'}]
    monkeypatch.setattr(watcher, 'session_visible', lambda *_: False)
    monkeypatch.setattr(watcher, 'find_visible_elements', lambda *_: [password])
    monkeypatch.setattr(
        watcher,
        'rendered_text',
        lambda *_: 'Guthaben Datenvolumen Inland',
    )

    assert watcher.aldi_session_visible(driver) is False


def test_protected_content_fallback_needs_multiple_marker_groups(monkeypatch):
    driver = Mock(current_url=watcher.ALDI_OVERVIEW_URL)
    driver.get_cookies.return_value = [{'name': 'session', 'value': 'PRIVATE'}]
    monkeypatch.setattr(watcher, 'session_visible', lambda *_: False)
    monkeypatch.setattr(watcher, 'find_visible_elements', lambda *_: [])
    monkeypatch.setattr(watcher, 'rendered_text', lambda *_: 'Guthaben')

    assert watcher.aldi_session_visible(driver) is False


def test_ambiguous_username_never_receives_credentials(login_page, monkeypatch):
    driver, user, password, submit, _ = login_page
    other_user = Mock()
    other_user.is_enabled.return_value = True
    other_user.get_attribute.return_value = None
    monkeypatch.setattr(watcher, 'find_visible_elements', lambda *_: [user, other_user])
    with pytest.raises(TimeoutException):
        watcher.aldi_login(driver)
    user.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()
    submit.send_keys.assert_not_called()
    driver.execute_script.assert_not_called()


def test_uncertain_pointer_submit_is_not_repeated(login_page):
    driver, user, password, submit, _ = login_page
    def uncertain_press(method, params):
        if params['type'] == 'mousePressed':
            raise TimeoutException('PRIVATE upstream content')
    driver.execute_cdp_cmd.side_effect = uncertain_press
    with pytest.raises(TimeoutException):
        watcher.aldi_login(driver)
    assert user.send_keys.call_args_list == [
        call(Keys.CONTROL, 'a'), call(Keys.BACKSPACE), call('PRIVATE_USER'), call(Keys.TAB)
    ]
    assert password.send_keys.call_args_list == [
        call(Keys.CONTROL, 'a'), call(Keys.BACKSPACE), call('PRIVATE_PASSWORD'), call(Keys.TAB)
    ]
    submit.click.assert_not_called()
    submit.send_keys.assert_not_called()
    assert [item.args[1]['type'] for item in driver.execute_cdp_cmd.call_args_list] == ['mouseMoved', 'mousePressed']
    assert all('.click(' not in item.args[0] for item in driver.execute_script.call_args_list)


@pytest.mark.parametrize("inactive_kind", ["disabled", "aria_disabled", "readonly"])
def test_inactive_extra_username_does_not_block_active_field(login_page, monkeypatch, inactive_kind):
    driver, user, password, submit, _ = login_page
    inactive = Mock()
    inactive.is_enabled.return_value = inactive_kind != "disabled"
    inactive.get_attribute.side_effect = lambda name: (
        "true" if name == "aria-disabled" and inactive_kind == "aria_disabled"
        else "" if name == "readonly" and inactive_kind == "readonly" else None
    )
    original = watcher.find_visible_elements
    monkeypatch.setattr(watcher, "find_visible_elements", lambda d, selector:
                        [inactive, user] if "autocomplete" in selector else original(d, selector))
    assert watcher.aldi_login(driver)
    inactive.send_keys.assert_not_called()
    assert call("PRIVATE_USER") in user.send_keys.call_args_list
    assert_native_login_once(driver, submit)


@pytest.mark.parametrize("control", ["username", "submit"])
def test_rerender_during_control_search_is_requeried_before_submission(login_page, monkeypatch, control):
    driver, user, password, submit, _ = login_page
    stale = Mock()
    stale.is_enabled.side_effect = StaleElementReferenceException("PRIVATE DOM")
    original = watcher.find_visible_elements
    searches = 0
    def elements(d, selector):
        nonlocal searches
        target = "autocomplete" in selector if control == "username" else "button,a" in selector
        if target:
            searches += 1
            if searches == 1:
                return [stale]
        return original(d, selector)
    monkeypatch.setattr(watcher, "find_visible_elements", elements)
    assert watcher.aldi_login(driver)
    assert searches == 2
    stale.send_keys.assert_not_called()
    assert_native_login_once(driver, submit)


def test_stale_submission_is_not_repeated(login_page):
    driver, _, _, submit, _ = login_page
    driver.execute_script.side_effect = StaleElementReferenceException("PRIVATE DOM")
    with pytest.raises(StaleElementReferenceException):
        watcher.aldi_login(driver)
    assert driver.execute_script.call_count == 1
    driver.execute_cdp_cmd.assert_not_called()


@pytest.mark.parametrize('invalid_rect', [
    None, {'x': 0},
    {'x': float('nan')}, {'w': float('inf')}, {'h': 0}, {'w': True},
    {'x': -1}, {'y': -1}, {'vw': 50}, {'vh': 30},
])
def test_native_pointer_rejects_unverified_or_outside_viewport_rect(login_page, invalid_rect):
    driver, _, _, submit, _ = login_page
    rect = dict(driver.execute_script.return_value)
    rect = None if invalid_rect is None else dict(rect, **invalid_rect)
    if invalid_rect == {'x': 0}:
        rect.pop('vw')
    driver.execute_script.return_value = rect
    with pytest.raises(RuntimeError, match='pointer_control_not_in_viewport'):
        trusted_pointer_click(driver, submit, lambda: None)
    driver.execute_cdp_cmd.assert_not_called()
    submit.click.assert_not_called()


def test_origin_change_on_pointer_move_blocks_pointer_down(login_page):
    driver, _, _, submit, _ = login_page
    def navigate_on_move(method, params):
        if params['type'] == 'mouseMoved':
            driver.current_url = 'https://attacker.invalid/'
    driver.execute_cdp_cmd.side_effect = navigate_on_move
    with pytest.raises(PermissionError):
        trusted_pointer_click(driver, submit, lambda: watcher.require_origin(
            driver, watcher.ALDI_LOGIN_URL, login_hosts=watcher.ALDI_LOGIN_HOSTS))
    assert [item.args[1]['type'] for item in driver.execute_cdp_cmd.call_args_list] == ['mouseMoved']
    submit.click.assert_not_called()


def test_pointer_release_failure_never_repeats_submission_or_falls_back(login_page):
    driver, _, _, submit, _ = login_page
    def uncertain_release(method, params):
        if params['type'] == 'mouseReleased':
            raise WebDriverException('PRIVATE_PROVIDER_OUTCOME')
    driver.execute_cdp_cmd.side_effect = uncertain_release
    with pytest.raises(WebDriverException):
        watcher.aldi_login(driver)
    assert_native_login_once(driver, submit)


def test_disabled_control_after_pointer_move_cannot_submit(login_page):
    driver, _, _, submit, _ = login_page
    def disable_on_move(method, params):
        if params['type'] == 'mouseMoved':
            submit.is_enabled.return_value = False
    driver.execute_cdp_cmd.side_effect = disable_on_move
    with pytest.raises(RuntimeError, match='pointer_control_became_disabled'):
        trusted_pointer_click(driver, submit, lambda: None)
    assert [item.args[1]['type'] for item in driver.execute_cdp_cmd.call_args_list] == ['mouseMoved']
    submit.click.assert_not_called()
