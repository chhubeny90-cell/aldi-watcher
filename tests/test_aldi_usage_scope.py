"""Domestic usage must not fall back to an unrelated roaming allowance."""
from unittest.mock import Mock

import pytest

import watcher


@pytest.mark.parametrize('page_text', [
    'Guthaben EU Roaming: 5 GB verfügbar',
    'Guthaben Restvolumen: 0 MB Inland Datenpaket: 25 GB',
])
def test_unscoped_page_volume_is_not_domestic_usage(monkeypatch, page_text):
    driver = Mock()
    # A real DOM with adjacent Inland/Roaming blocks made the old ancestor XPath
    # select their shared page container. Even a matching old scope is unsafe.
    driver.find_element.return_value.find_element.return_value.text = page_text
    monkeypatch.setattr(watcher, 'navigate', lambda *_: None)
    monkeypatch.setattr(watcher, 'require_origin', lambda *_: None)
    monkeypatch.setattr(watcher, 'session_visible', lambda _: True)
    monkeypatch.setattr(watcher, 'rendered_text', lambda _: page_text)
    monkeypatch.setattr(watcher.time, 'sleep', lambda _: None)

    status = watcher.aldi_read_status(driver)

    assert status['inland_frei_gb'] is None
    # Composed text has no account-safe line boundaries for retaining a balance.
    assert page_text not in status.values()
