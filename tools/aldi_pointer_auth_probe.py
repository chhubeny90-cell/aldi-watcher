"""Run the sanitized ALDI auth probe with one trusted pointer submit.

This diagnostic wrapper changes only the already validated `Anmelden` control
activation: the JavaScript DOM click is replaced by one WebDriver ActionChains
pointer click. It does not add retries, refill actions, or booking capability.
"""
from selenium.webdriver.common.action_chains import ActionChains

import watcher
from browser_dom import element_label
from tools import aldi_auth_probe


_original_build_driver = watcher.build_driver


def _build_driver_with_pointer_submit():
    driver = _original_build_driver()
    original_execute_script = driver.execute_script

    def execute_script(script, *args):
        if script.strip() == "arguments[0].click();" and len(args) == 1:
            try:
                label = element_label(driver, args[0]).strip().casefold()
            except Exception:
                label = ""
            if label == "anmelden":
                ActionChains(driver).move_to_element(args[0]).click().perform()
                return None
        return original_execute_script(script, *args)

    driver.execute_script = execute_script
    return driver


watcher.build_driver = _build_driver_with_pointer_submit


if __name__ == "__main__":
    raise SystemExit(aldi_auth_probe.main())
