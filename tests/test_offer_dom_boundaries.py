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


def test_button_context_climbs_to_sibling_price_but_not_past_ambiguous_card(monkeypatch):
    import browser_dom
    class Node:
        def __init__(self, text, tag, parent=None):
            self.text, self.tag_name, self.parent = text, tag, parent
    card = Node('0,00 €\n1 GB nachbuchen', 'section')
    button = Node('1 GB nachbuchen', 'button', card)
    class Driver:
        def execute_script(self, _, node):
            return node.parent
    monkeypatch.setattr(browser_dom, 'rendered_offer_text', lambda _, n: n.text)
    monkeypatch.setattr(browser_dom, 'find_visible_elements', lambda *_, **__: [button])
    assert _offer_context(Driver(), button) == card.text
    monkeypatch.setattr(browser_dom, 'find_visible_elements', lambda *_, **__: [button, Node('other', 'button')])
    assert _offer_context(Driver(), button) == ''
