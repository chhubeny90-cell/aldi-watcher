from unittest.mock import Mock, call
import pytest
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
import watcher


@pytest.fixture
def login_page(monkeypatch):
    driver = Mock(current_url=watcher.ALDI_LOGIN_URL)
    user, password, submit = (Mock() for _ in range(3))
    for control in (user, password, submit):
        control.is_enabled.return_value = True
        control.get_attribute.return_value = None
    monkeypatch.setattr(watcher, 'ALDI_USER', 'PRIVATE_USER')
    monkeypatch.setattr(watcher, 'ALDI_PASS', 'PRIVATE_PASSWORD')
    monkeypatch.setattr(watcher, 'navigate', lambda *_: None)
    monkeypatch.setattr(watcher, 'dismiss_cookie_banner', lambda *_: None)
    monkeypatch.setattr(watcher, 'element_label', lambda *_: 'Anmelden')
    monkeypatch.setattr(watcher, 'aldi_protected_session_visible', lambda *_: True)
    monkeypatch.setattr(watcher, 'WAIT_TIMEOUT', .01)
    def elements(_, selector):
        if 'autocomplete' in selector:
            return [user]
        if 'password' in selector:
            return [password]
        return [submit]
    monkeypatch.setattr(watcher, 'find_visible_elements', elements)
    return driver, user, password, submit


def test_shadow_controls_are_filled_and_submitted_once(login_page):
    driver, user, password, submit = login_page
    assert watcher.aldi_login(driver)
    user.send_keys.assert_called_once_with('PRIVATE_USER')
    assert password.send_keys.call_args_list == [call('PRIVATE_PASSWORD'), call(Keys.ENTER)]
    submit.click.assert_not_called()
    driver.execute_script.assert_not_called()


def test_untrusted_origin_never_receives_credentials(login_page):
    driver, user, password, submit = login_page
    driver.current_url = 'https://attacker.invalid/'
    with pytest.raises(PermissionError):
        watcher.aldi_login(driver)
    user.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()


def test_ambiguous_username_never_receives_credentials(login_page, monkeypatch):
    driver, user, password, submit = login_page
    monkeypatch.setattr(watcher, 'find_visible_elements', lambda *_: [user, Mock()])
    with pytest.raises(TimeoutException):
        watcher.aldi_login(driver)
    user.send_keys.assert_not_called()
    password.send_keys.assert_not_called()
    submit.click.assert_not_called()


def test_uncertain_enter_submit_is_not_repeated(login_page):
    driver, user, password, submit = login_page
    password.send_keys.side_effect = [None, TimeoutException('PRIVATE upstream content')]
    with pytest.raises(TimeoutException):
        watcher.aldi_login(driver)
    assert password.send_keys.call_args_list == [call('PRIVATE_PASSWORD'), call(Keys.ENTER)]
    submit.click.assert_not_called()
