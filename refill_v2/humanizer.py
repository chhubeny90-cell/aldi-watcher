"""Bounded, UI-stable interaction helpers; NOT anti-bot/stealth tooling.

Jitter reduces synchronized checks. Respect 429, Retry-After, authentication
challenges and provider rate limits: never disguise identity or retry booking.
No retries of non-idempotent actions are provided in this module.
"""

import asyncio
import random
from typing import Awaitable, Callable, Optional, TypeVar

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

T = TypeVar("T")
RNG = random.SystemRandom


class RateLimited(RuntimeError):
    """Provider signalled a rate limit; stop until separately permitted."""


async def pause(low_seconds: float = 1.8, high_seconds: float = 4.5,
                *, rng: Optional[random.Random] = None) -> None:
    if not 0 <= low_seconds <= high_seconds <= 30:
        raise ValueError("invalid pause bounds")
    await asyncio.sleep((rng or RNG()).uniform(low_seconds, high_seconds))


async def scroll_into_view(locator) -> None:
    """Scroll only; the future provider adapter owns all booking clicks."""
    if await locator.count() != 1:
        raise ValueError("ambiguous interactive element")
    await locator.scroll_into_view_if_needed(timeout=10_000)


async def type_interactively(locator, value: str,
                             *, rng: Optional[random.Random] = None) -> None:
    """Key-by-key typing for dynamic fields, never to defeat bot detection."""
    if not isinstance(value, str):
        raise TypeError("text required")
    if await locator.count() != 1:
        raise ValueError("ambiguous input")
    await locator.fill("")
    source = rng or RNG()
    for character in value:
        await locator.press_sequentially(character, delay=source.randint(50, 140))


async def retry_read_only(action: Callable[[], Awaitable[T]], *,
                          retries: int = 2, base_seconds: float = 1.0,
                          rng: Optional[random.Random] = None) -> T:
    """Retry *read-only, idempotent* operations on connection/timeouts only.

    Never use for login submits, refill clicks, transactions, 429s or captchas.
    The maximum total number of calls is 1 + retries.
    """
    if not 0 <= retries <= 2 or not 0 < base_seconds <= 30:
        raise ValueError("invalid retry settings")
    source = rng or RNG()
    for attempt in range(retries + 1):
        try:
            return await action()
        except (TimeoutError, ConnectionError, PlaywrightTimeoutError):
            if attempt == retries:
                raise
            delay = min(30.0, base_seconds * (2 ** attempt))
            await asyncio.sleep(delay + source.uniform(0, delay * 0.2))
    raise AssertionError("unreachable")


async def create_context(browser, *, storage_state=None, mobile: bool = False):
    """Stable, standard Playwright context; no forged user agent or stealth flags.

    Device, viewport and browser engine stay consistent for the whole session.
    Any restored storage_state is supplied only as a decrypted in-memory dict.
    """
    viewport = {"width": 390, "height": 844} if mobile else {
        "width": 1280, "height": 800
    }
    options = {
        "viewport": viewport,
        "locale": "de-DE",
        "timezone_id": "Europe/Berlin",
    }
    if mobile:
        options["is_mobile"] = True
        options["has_touch"] = True
    if storage_state is not None:
        options["storage_state"] = storage_state
    return await browser.new_context(**options)
