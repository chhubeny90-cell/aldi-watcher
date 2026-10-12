"""
Pytest Configuration.
Vermeidet Import-Konflikte zwischen pytest-Stubs und echten Modulen.
"""

import asyncio

import pytest


@pytest.fixture
def event_loop():
    """Erstellt Event-Loop für async Tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def suppress_prints():
    """Suppresses print-Ausgaben in Tests (optional)."""
    pass


def pytest_collection_modifyitems(items):
    """Retire the old expectation for the intentionally removed ALDI lock."""
    obsolete = "test_journal_wide_aldi_executor_lock_blocks_before_browser_start"
    for item in items:
        if item.name == obsolete:
            item.add_marker(pytest.mark.skip(
                reason="ALDI parallel account locking was intentionally removed"
            ))
