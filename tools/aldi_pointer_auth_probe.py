"""Run the sanitized ALDI auth probe with one trusted pointer submit.

The production watcher submits the already validated `Anmelden` control with
one ENTER key. This diagnostic wrapper replaces only that one ENTER activation
with a WebDriver ActionChains pointer click. It does not alter username/password
input, add retries, touch refill controls, or add booking capability.
"""
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement

import watcher
from browser_dom import element_label
from tools import aldi_auth_probe


_original_build_driver = watcher.build_driver
_original_send_keys = WebElement.send_keys


def _build_driver_with_pointer_submit():
    driver = _original_build_driver()

    def send_keys(element, *value):
        if value == (Keys.ENTER,):
            try:
                label = element_label(driver, element).strip().casefold()
            except Exception:
                label = ''
            if label == 'anmelden':
                ActionChains(driver).move_to_element(element).click().perform()
                return None
        return _original_send_keys(element, *value)

    WebElement.send_keys = send_keys
    return driver


watcher.build_driver = _build_driver_with_pointer_submit


if __name__ == '__main__':
    raise SystemExit(aldi_auth_probe.main())
