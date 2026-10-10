from unittest.mock import Mock, call
import pytest
from selenium.common.exceptions import TimeoutException
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
    submit.click.assert_called_once_with()
    submit.send_keys.assert_not_called()
    navigate_mock.assert_called_once_with(driver, watcher.ALDI_LOGIN_URL)
    driver.execute_script.assert_not_called()


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
    submit.click.assert_called_once_with()
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
    submit.click.assert_called_once_with()
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
    monkeypatch.setattr(watcher, 'find_visible_elements', lambda *_: [user, Mock()])
    with pytest.raises(TimeoutException):
        watcher.aldi_login(driver)
    user.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()
    submit.send_keys.assert_not_called()
    driver.execute_script.assert_not_called()


def test_uncertain_native_click_is_not_repeated(login_page):
    driver, user, password, submit, _ = login_page
    submit.click.side_effect = TimeoutException('PRIVATE upstream content')
    with pytest.raises(TimeoutException):
        watcher.aldi_login(driver)
    assert user.send_keys.call_args_list == [
        call(Keys.CONTROL, 'a'), call(Keys.BACKSPACE), call('PRIVATE_USER'), call(Keys.TAB)
    ]
    assert password.send_keys.call_args_list == [
        call(Keys.CONTROL, 'a'), call(Keys.BACKSPACE), call('PRIVATE_PASSWORD'), call(Keys.TAB)
    ]
    submit.click.assert_called_once_with()
    submit.send_keys.assert_not_called()
    driver.execute_script.assert_not_called()
