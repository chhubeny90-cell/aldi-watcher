"""Run the sanitized ALDI auth probe with one password-field ENTER submit.

The production watcher validates the unique ``Anmelden`` control before
submitting. This diagnostic wrapper keeps that validation, but replaces only
the final ENTER on that control with one ENTER key sent to the unique visible
password field. This tests the component's keyboard-submit path without retries,
JavaScript clicks, refill actions, or booking capability.
"""
from selenium.common.exceptions import InvalidElementStateException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement

import watcher
from browser_dom import element_label, find_visible_elements
from tools import aldi_auth_probe


_original_build_driver = watcher.build_driver
_original_send_keys = WebElement.send_keys


def _build_driver_with_password_enter():
    driver = _original_build_driver()

    def send_keys(element, *value):
        if value == (Keys.ENTER,):
            try:
                label = element_label(driver, element).strip().casefold()
            except Exception:
                label = ''
            if label == 'anmelden':
                passwords = find_visible_elements(driver, "input[type='password']")
                if len(passwords) != 1 or not passwords[0].is_enabled():
                    raise InvalidElementStateException(
                        'Unique enabled password field required for diagnostic submit'
                    )
                return _original_send_keys(passwords[0], Keys.ENTER)
        return _original_send_keys(element, *value)

    WebElement.send_keys = send_keys
    return driver


watcher.build_driver = _build_driver_with_password_enter


if __name__ == '__main__':
    raise SystemExit(aldi_auth_probe.main())
