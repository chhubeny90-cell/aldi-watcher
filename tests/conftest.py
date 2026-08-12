"""
Pytest Configuration.
Vermeidet Import-Konflikte zwischen pytest-Stubs und echten Modulen.
"""

import pytest
import asyncio


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
