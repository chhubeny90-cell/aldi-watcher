"""Local composed-DOM regressions; opt in with RUN_BROWSER_DOM_TESTS=1.

The ordinary test suite needs no installed browser. Browser checks use only a
local HTML fixture, without provider requests or credentials.
"""
import os
import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from selenium.common.exceptions import TimeoutException
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from browser_dom import element_label, find_visible_elements, rendered_text


HTML = """<!doctype html><html><body>
<p>Ordinary page text</p>
<input id="ordinary" type="text">
<div hidden><input id="hidden-ordinary"><span>HIDDEN ORDINARY</span></div>
<template><input id="template-input">HIDDEN TEMPLATE</template>
<div style="opacity:0"><input id="transparent"><span>HIDDEN TRANSPARENT</span></div>
<input type="password" value="PRIVATE FORM VALUE">
<div id="login"></div>
<div id="other"></div>
<script>
(() => {
const login = document.querySelector('#login').attachShadow({mode: 'open'});
login.innerHTML = `<div id="fields"></div><div id="submit"></div>
  <div hidden><input id="hidden-shadow">HIDDEN SHADOW</div>`;
const fields = login.querySelector('#fields').attachShadow({mode: 'open'});
fields.innerHTML = `<label>Rufnummer <input id="username" autocomplete="username"></label>
  <label>Passwort <input id="password" type="password" autocomplete="current-password"></label>
  <p>Restvolumen: <span>1 GB</span> verfügbar</p>`;
const submitHost = login.querySelector('#submit');
submitHost.innerHTML = `<span slot="label">Anmelden</span>`;
submitHost.attachShadow({mode: 'open'}).innerHTML =
  `<a id="submit-anchor" role="link" type="button" tabindex="0"><slot name="label"></slot></a>`;
const other = document.querySelector('#other').attachShadow({mode: 'open'});
other.innerHTML = `<button id="faq" aria-label="FAQ"></button>
  <div id="fallback"><span>Host label</span></div>
  <div id="multi"></div>`;
other.querySelector('#fallback').attachShadow({mode: 'open'}).innerHTML =
  `<button id="empty-button"></button><slot></slot>`;
other.querySelector('#multi').attachShadow({mode: 'open'}).innerHTML =
  `<input type="password"><button id="toggle"></button><p>Anmelden</p>`;
})();
</script>
</body></html>"""


@pytest.fixture(scope='module')
def local_browser():
    if os.getenv('RUN_BROWSER_DOM_TESTS') != '1':
        pytest.skip('Set RUN_BROWSER_DOM_TESTS=1 to run local browser integration checks')
    binary = os.getenv('CHROME_BINARY') or shutil.which('chromium') or shutil.which('google-chrome')
    if not binary:
        pytest.fail('Local browser checks require CHROME_BINARY or an installed Chromium')
    options = Options()
    options.binary_location = binary
    for argument in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage'):
        options.add_argument(argument)
    path = os.getenv('CHROMEDRIVER_PATH') or shutil.which('chromedriver')
    service = Service(executable_path=path) if path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    try:
        driver.get('about:blank')
        driver.execute_script(
            'document.open(); document.write(arguments[0]); document.close();', HTML,
        )
        yield driver
    finally:
        driver.quit()


def test_accessible_name_has_priority_and_is_normalized(capsys):
    driver = Mock()
    element = SimpleNamespace(accessible_name='  Anmelden\n  jetzt  ')
    assert element_label(driver, element) == 'Anmelden jetzt'
    driver.execute_script.assert_not_called()
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('selector', ['', '  ', None, 1])
def test_missing_selector_is_rejected_before_browser_access(selector):
    driver = Mock()
    with pytest.raises(ValueError, match='CSS selector'):
        find_visible_elements(driver, selector)
    driver.execute_script.assert_not_called()


def test_visible_native_inputs_include_nested_shadow_and_light_dom(local_browser):
    elements = find_visible_elements(local_browser, 'input')
    identifiers = {element.get_attribute('id') for element in elements}
    assert {'ordinary', 'username', 'password'} <= identifiers
    assert not {'hidden-ordinary', 'hidden-shadow', 'template-input', 'transparent'} & identifiers
    username = find_visible_elements(local_browser, 'input[autocomplete="username"]')
    assert len(username) == 1
    # Native WebElements stay usable for normal Selenium interactions.
    username[0].send_keys('fixture user')
    assert username[0].get_attribute('value') == 'fixture user'


def test_scope_includes_own_shadow_root_and_excludes_other_components(local_browser):
    login = local_browser.find_element('css selector', '#login')
    assert {element.get_attribute('id') for element in find_visible_elements(local_browser, 'input', login)} == {
        'username', 'password',
    }
    assert find_visible_elements(local_browser, 'button', login) == []


def test_rendered_text_includes_slots_once_and_excludes_hidden_sources(local_browser):
    text = rendered_text(local_browser)
    assert 'Ordinary page text' in text
    assert 'Restvolumen: 1 GB verfügbar' in text
    assert text.count('Anmelden') == 2
    assert 'HIDDEN' not in text
    assert 'PRIVATE FORM VALUE' not in text
    assert 'attachShadow' not in text
    login = local_browser.find_element('css selector', '#login')
    assert rendered_text(local_browser, login).count('Anmelden') == 1
    assert 'Ordinary page text' not in rendered_text(local_browser, login)


def test_action_labels_cover_anchor_slots_accessibility_and_isolated_hosts(local_browser):
    elements = find_visible_elements(local_browser, 'a, button')
    by_id = {element.get_attribute('id'): element for element in elements}
    assert element_label(local_browser, by_id['submit-anchor']) == 'Anmelden'
    assert element_label(local_browser, by_id['faq']) == 'FAQ'
    assert element_label(local_browser, by_id['empty-button']) == 'Host label'
    # A form's unrelated text must not label its password-toggle button.
    assert element_label(local_browser, by_id['toggle']) == ''


@pytest.mark.parametrize('ambiguous_submit', [False, True])
def test_aldi_login_submits_only_one_exact_shadow_action(local_browser, monkeypatch, ambiguous_submit):
    import watcher

    # Isolate one login form; unrelated password controls above remain useful in
    # the generic helper fixture but are deliberately absent from this scenario.
    local_browser.execute_script('''
        document.querySelector('body > input[type="password"]').remove();
        document.querySelector('#other').remove();
        window.submitCount = 0;
    ''')
    try:
        actions = find_visible_elements(local_browser, 'a')
        assert len(actions) == 1
        local_browser.execute_script('''
            arguments[0].addEventListener('click', () => window.submitCount++);
        ''', actions[0])
        if ambiguous_submit:
            local_browser.execute_script('''
                const duplicate = document.createElement('a');
                duplicate.setAttribute('role', 'link');
                duplicate.textContent = 'Anmelden';
                arguments[0].getRootNode().appendChild(duplicate);
            ''', actions[0])
        monkeypatch.setattr(watcher, 'ALDI_USER', 'fixture user')
        monkeypatch.setattr(watcher, 'ALDI_PASS', 'fixture password')
        monkeypatch.setattr(watcher, 'WAIT_TIMEOUT', .1)
        monkeypatch.setattr(watcher, 'navigate', lambda *_: None)
        origin_check = Mock()
        monkeypatch.setattr(watcher, 'require_origin', origin_check)
        monkeypatch.setattr(watcher, 'session_visible', lambda driver: bool(
            driver.execute_script('return window.submitCount;')))

        if ambiguous_submit:
            with pytest.raises(TimeoutException):
                watcher.aldi_login(local_browser)
            assert local_browser.execute_script('return window.submitCount;') == 0
        else:
            assert watcher.aldi_login(local_browser)
            assert local_browser.execute_script('return window.submitCount;') == 1
            # Initial navigation plus guard before each field and submit.
            assert origin_check.call_count == 4
    finally:
        local_browser.execute_script(
            'document.open(); document.write(arguments[0]); document.close();', HTML,
        )
