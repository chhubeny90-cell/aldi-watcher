"""Real offline Chromium rendering; no ALDI page, account or network."""
from pathlib import Path
import os
import pytest
from browser_dom import _DOM_HELPERS
from core.aldi_refill import assess_refill, _offer_context


@pytest.fixture(scope='module')
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        executable = os.environ.get('CHROME_BINARY') or p.chromium.executable_path
        if not Path(executable).exists():
            if os.environ.get('REQUIRE_OFFLINE_BROWSER') == 'true':
                pytest.fail('required offline Chromium fixture unavailable')
            pytest.skip('offline Chromium fixture requires playwright install chromium')
        browser = p.chromium.launch(executable_path=executable, headless=True, args=['--no-sandbox'])
        page = browser.new_page()
        page.route('**/*', lambda route: route.abort())
        yield page
        browser.close()


@pytest.mark.parametrize('wallet,price,allowed', [
    ('<div>Guthaben 14,95 €</div>', '<div>0,00 €</div>', True),
    ('<span>Guthaben 14,95 €</span>', '<span>0,00 €</span>', False),
    ('<div>Guthaben 14,95 €</div>', '<div>2,99 €</div>', False),
    ('<div>Guthaben 0,00 €</div>', '', False),
])
def test_visible_field_boundaries_do_not_invent_free_price(page, wallet, price, allowed):
    page.set_content(f'<section id="card">{wallet}{price}<button>1 GB nachbuchen</button></section>')
    text = page.evaluate('() => {' + _DOM_HELPERS + ';return renderedText(document.querySelector("#card"), true)}')
    result = assess_refill('Tarif S Unlimited', text, '1 GB nachbuchen', True, 1, 0.4)
    assert result['refill_eligible'] is allowed


def test_shadow_and_slot_keep_real_wallet_block_separation(page):
    page.set_content('<div id="card"><div>Guthaben 14,95 €</div><x-refill><span>1 GB nachbuchen</span></x-refill></div>')
    page.evaluate('''() => document.querySelector('x-refill').attachShadow({mode:'open'}).innerHTML =
        '<div>0,00 €</div><button><slot></slot></button>' ''')
    text = page.evaluate('() => {' + _DOM_HELPERS + ';return renderedText(document.querySelector("#card"), true)}')
    assert 'Guthaben 14,95 €\n' in text
    assert assess_refill('Tarif S Unlimited', text, '1 GB nachbuchen', True, 1, 0.4)['refill_eligible']


def test_unpriced_button_cannot_borrow_sibling_or_page_wrapper_price(monkeypatch):
    import browser_dom
    class Node:
        def __init__(self, text): self.text = text
    button = Node('1 GB nachbuchen')
    monkeypatch.setattr(browser_dom, 'rendered_offer_text', lambda _, n: n.text)
    class Driver:
        def execute_script(self, *_):
            pytest.fail('ancestor search must not run')
    context = _offer_context(Driver(), button)
    assert context == '1 GB nachbuchen'
    assert not assess_refill('Tarif S Unlimited', context, button.text, True, 1, .4)['refill_eligible']


def test_priced_control_uses_only_its_own_rendered_subtree(monkeypatch):
    import browser_dom
    button = object()
    monkeypatch.setattr(browser_dom, 'rendered_offer_text', lambda _, n: '1 GB nachbuchen 0,00 €' if n is button else pytest.fail('wrong scope'))
    context = _offer_context(object(), button)
    assert assess_refill('Tarif S Unlimited', context, '1 GB nachbuchen', True, 1, .4)['refill_eligible']


def test_real_dom_unrelated_free_field_is_not_an_offer_price(page):
    page.set_content('<main><div>Sonstige Kosten 0,00 €</div><section><button id="action">1 GB nachbuchen</button></section></main>')
    class Driver:
        def execute_script(self, script, _):
            return page.evaluate('() => {' + _DOM_HELPERS + ';return renderedText(document.querySelector("#action"), true)}')
    context = _offer_context(Driver(), object())
    assert not assess_refill('Tarif S Unlimited', context, '1 GB nachbuchen', True, 1, .4)['refill_eligible']
