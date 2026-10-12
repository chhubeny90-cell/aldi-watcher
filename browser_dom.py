"""Read rendered elements and text across open shadow roots with Selenium.

CSS selectors apply within each DOM root; they cannot cross a shadow boundary.
These helpers return data to the caller and never log page or account content.
"""

import math


_DOM_HELPERS = r"""
function composedParent(element) {
    return element.assignedSlot || element.parentElement ||
        (element.getRootNode && element.getRootNode().host) || null;
}

function renderedStyle(element) {
    for (let current = element; current; current = composedParent(current)) {
        const style = getComputedStyle(current);
        if (current.hidden || style.display === 'none' ||
            style.visibility === 'hidden' || style.visibility === 'collapse' ||
            Number(style.opacity) === 0) return false;
    }
    return true;
}

function visible(element) {
    return renderedStyle(element) && Array.from(element.getClientRects()).some(
        rect => rect.width > 0 && rect.height > 0);
}

function queryDeep(root, selector) {
    const found = [];
    const seen = new Set();
    function visit(current) {
        for (const element of current.querySelectorAll(selector)) {
            if (!seen.has(element) && visible(element)) {
                seen.add(element);
                found.push(element);
            }
        }
        if (current.shadowRoot) visit(current.shadowRoot);
        for (const element of current.querySelectorAll('*')) {
            if (element.shadowRoot) visit(element.shadowRoot);
        }
    }
    visit(root);
    return found;
}

function renderedText(root) {
    const parts = [];
    const seen = new Set();
    function visit(node) {
        if (seen.has(node)) return;
        seen.add(node);
        if (node.nodeType === Node.TEXT_NODE) {
            if (!node.textContent.trim() || !node.parentElement ||
                !renderedStyle(node.parentElement)) return;
            const range = document.createRange();
            range.selectNodeContents(node);
            if (Array.from(range.getClientRects()).some(
                    rect => rect.width > 0 && rect.height > 0)) {
                parts.push(node.textContent);
            }
            return;
        }
        if (node.nodeType === Node.ELEMENT_NODE) {
            // Form values and template/script source are not rendered page text.
            if (['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT', 'INPUT', 'TEXTAREA'].includes(node.tagName) ||
                !renderedStyle(node)) return;
            if (node.tagName === 'SLOT') {
                const assigned = node.assignedNodes({flatten: true});
                for (const child of assigned.length ? assigned : node.childNodes) visit(child);
                return;
            }
            if (node.shadowRoot) {
                visit(node.shadowRoot);
                return;
            }
        }
        for (const child of node.childNodes) visit(child);
    }
    visit(root);
    return parts.join(' ').replace(/\s+/g, ' ').trim();
}

function label(element) {
    const own = element.getAttribute('aria-label') || renderedText(element) ||
        element.getAttribute('title') ||
        (['submit', 'button'].includes(element.type) ? element.value : '');
    if (own) return own;
    // Some components keep their label beside the native action in a shadow root.
    // Stop before a host with other controls, so a surrounding form's text cannot
    // turn a password toggle or unrelated action into the submit control.
    let current = element;
    while (current.getRootNode().host) {
        const host = current.getRootNode().host;
        const controls = queryDeep(host, 'button, input, select, textarea, a[href], a[role], [role="button"]');
        if (controls.length !== 1 || controls[0] !== element) return '';
        const text = host.getAttribute('aria-label') || renderedText(host);
        if (text) return text;
        current = host;
    }
    return '';
}
"""


def find_visible_elements(driver, selector, scope=None):
    """Return visible CSS matches, including nested open shadow roots.

    Optional scope is a WebElement. As with WebElement.find_elements(), matching
    considers its descendants, including descendants of its own shadow root.
    Closed shadow roots and frame documents are separate inaccessible contexts.
    """
    if not isinstance(selector, str) or not selector.strip():
        raise ValueError('A nonempty CSS selector is required')
    return driver.execute_script(
        _DOM_HELPERS + '\nreturn queryDeep(arguments[1] || document, arguments[0]);',
        selector, scope,
    )


def rendered_text(driver, scope=None):
    """Return visible composed text once, excluding hidden templates/form values."""
    return driver.execute_script(
        _DOM_HELPERS + '\nreturn renderedText(arguments[0] || document.body);', scope,
    )


def element_label(driver, element):
    """Return a control's accessible name or composed component label."""
    accessible = getattr(element, 'accessible_name', '')
    if isinstance(accessible, str) and accessible.strip():
        return ' '.join(accessible.split())
    value = driver.execute_script(_DOM_HELPERS + '\nreturn label(arguments[0]);', element)
    return ' '.join((value or '').split())


def trusted_pointer_click(driver, element, check_origin):
    """One native pointer activation of an already-validated control, no retries.

    The caller supplies its origin guard. A failed pointer-down/release is an
    uncertain action: this helper never falls back to DOM click or submits again.
    """
    check_origin()
    rect = driver.execute_script(
        "arguments[0].scrollIntoView({block:'center',inline:'center'});"
        "const r=arguments[0].getBoundingClientRect();"
        "return {x:r.left,y:r.top,w:r.width,h:r.height,vw:innerWidth,vh:innerHeight};",
        element,
    )
    fields = ('x', 'y', 'w', 'h', 'vw', 'vh')
    if (not isinstance(rect, dict)
            or any(type(rect.get(key)) not in (int, float) or not math.isfinite(rect[key]) for key in fields)
            or rect['w'] <= 1 or rect['h'] <= 1 or rect['vw'] <= 0 or rect['vh'] <= 0
            or rect['x'] < 0 or rect['y'] < 0
            or rect['x'] + rect['w'] > rect['vw'] or rect['y'] + rect['h'] > rect['vh']):
        raise RuntimeError('pointer_control_not_in_viewport')
    x, y = rect['x'] + rect['w'] / 2, rect['y'] + rect['h'] / 2
    driver.execute_cdp_cmd('Input.dispatchMouseEvent', {
        'type': 'mouseMoved', 'x': x, 'y': y, 'button': 'none',
    })
    check_origin()  # Recheck immediately before any pointer-down can submit.
    if (not element.is_enabled() or element.get_attribute('disabled') is not None
            or element.get_attribute('aria-disabled') == 'true'):
        raise RuntimeError('pointer_control_became_disabled')
    driver.execute_cdp_cmd('Input.dispatchMouseEvent', {
        'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1,
    })
    driver.execute_cdp_cmd('Input.dispatchMouseEvent', {
        'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1,
    })
