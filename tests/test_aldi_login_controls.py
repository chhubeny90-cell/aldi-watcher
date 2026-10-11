from unittest.mock import Mock, call
import pytest
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from selenium.webdriver.common.keys import Keys
import watcher


@pytest.fixture
def login_page(monkeypatch):
    driver = Mock(current_url=watcher.ALDI_LOGIN_URL)
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
    driver.execute_script.assert_called_once_with('arguments[0].click();', submit)
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
    driver.execute_script.assert_called_once_with('arguments[0].click();', submit)
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
    driver.execute_script.assert_called_once_with('arguments[0].click();', submit)
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


def test_uncertain_dom_submit_is_not_repeated(login_page):
    driver, user, password, submit, _ = login_page
    driver.execute_script.side_effect = TimeoutException('PRIVATE upstream content')
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
    driver.execute_script.assert_called_once_with('arguments[0].click();', submit)


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
    driver.execute_script.assert_called_once_with('arguments[0].click();', submit)


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
    driver.execute_script.assert_called_once_with('arguments[0].click();', submit)


def test_stale_submission_is_not_repeated(login_page):
    driver, _, _, submit, _ = login_page
    driver.execute_script.side_effect = StaleElementReferenceException("PRIVATE DOM")
    with pytest.raises(StaleElementReferenceException):
        watcher.aldi_login(driver)
    driver.execute_script.assert_called_once_with('arguments[0].click();', submit)
