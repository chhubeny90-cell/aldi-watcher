"""LIDL usage monitoring and evidence-gated, free 1-GB browser refill.

The API URLs and usage selectors below are legacy integration assumptions,
not live-verified provider documentation. API booking is disabled. Protected
refill selectors must be supplied from an authenticated, observed account flow.
"""

import asyncio
import aiohttp
import re
import math
from urllib.parse import urlsplit
from core.lidl_refill import assess_refill, unavailable, configured_selectors
from typing import Dict, Optional
from playwright.async_api import async_playwright, Browser, Page
from .base_watcher import BaseWatcher, RechargeUnknownError


class LidlConnectWatcher(BaseWatcher):
    """
    Watcher fÃ¼r Lidl Connect Prepaid-Daten.
    PrimÃ¤r: API-basiert (aiohttp)
    Fallback: Playwright (Browser-Automatisierung)
    """

    # API-Endpoints
    API_HOST = "https://api.lidl-connect.de"
    API_AUTH = f"{API_HOST}/api/authenticate"
    API_CONSUMPTION = f"{API_HOST}/api/consumption"
    API_TARIFFS = f"{API_HOST}/api/tariff-options"
    API_BOOK = f"{API_HOST}/api/tariff-option/book"

    # Legacy login/usage selectors; validate against the actual account flow.
    # Quelle: https://kundenkonto.lidl-connect.de/mein-lidl-connect.html
    SELECTORS = {
        "username_input": "input[type='tel']",  # Rufnummer-Input
        "password_input": "input[type='password']",
        "login_button": "button[type='submit']",
        "data_usage": "div.consumption-tile",  # Haupt-Datenkachel
        "data_value": "span.consumption-value",  # Verbrauchswert
    }

    def __init__(self, username: str, password: str, threshold_mb: float, dry_run: bool = True, use_api: bool = False, database=None, refill_selectors=None, refill_mode="available"):
        super().__init__(username, password, threshold_mb, dry_run, database)
        self.use_api = use_api  # True = API, False = Playwright
        self.session: Optional[aiohttp.ClientSession] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.auth_token: Optional[str] = None
        self._playwright = None
        self.refill_selectors = configured_selectors() if refill_selectors is None else refill_selectors
        if refill_mode not in {"available", "needed"}:
            raise ValueError("LIDL_REFILL_MODE must be available or needed")
        self.refill_mode = refill_mode
        self.recharge_guard_seconds = 1800

    async def _exponential_backoff(self, func, max_retries: int = 5, base_delay: float = 1.0):
        """
        FÃ¼hrt func mit exponentiellem Backoff aus.
        FÃ¤ngt Timeouts/Captchas ab.
        """
        for attempt in range(max_retries):
            try:
                return await func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                
                delay = base_delay * (2 ** attempt)
                print(f"Lidl: Retry {attempt + 1}/{max_retries} after {delay}s (Error: {e})")
                await asyncio.sleep(delay)

    # ==================== API-METHODEN ====================

    async def _get_api_session(self) -> aiohttp.ClientSession:
        """Erstellt oder returniert existierende Session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def _api_login(self) -> str:
        """
        Login via API.
        Returns: Auth-Token fÃ¼r weitere Requests.
        """
        session = await self._get_api_session()
        
        async with session.post(
            self.API_AUTH,
            json={"username": self.username, "password": self.password}
        ) as response:
            if response.status != 200:
                raise Exception(f"Lidl API Login failed: {response.status}")
            
            data = await response.json()
            self.auth_token = data.get("token") or data.get("access_token")
            
            if not self.auth_token:
                raise Exception("Lidl API: No auth token in response")
            
            return self.auth_token

    async def _api_check_usage(self) -> Dict[str, float]:
        """
        PrÃ¼ft Datenvolumen via API.
        Returns: {"used_mb": float, "total_mb": float}
        """
        session = await self._get_api_session()
        
        # Login falls noch nicht authentifiziert
        if not self.auth_token:
            await self._api_login()
        
        async with session.get(
            self.API_CONSUMPTION,
            headers={"Authorization": f"Bearer {self.auth_token}"}
        ) as response:
            if response.status != 200:
                raise Exception(f"Lidl API Usage failed: {response.status}")
            
            data = await response.json()
            
            # Consumption-Daten extrahieren
            consumptions = data.get("consumptions", [])
            data_consumption = None
            
            for c in consumptions:
                if c.get("type") == "DATA":
                    data_consumption = c
                    break
            
            if not data_consumption:
                raise Exception("Lidl API: No DATA consumption found")
            
            consumed = float(data_consumption.get("consumed", 0))
            max_val = float(data_consumption.get("max", 0))
            unit = data_consumption.get("unit", "GB")
            
            # In MB umrechnen
            multiplier = 1024 if unit == "GB" else 1
            used_mb = consumed * multiplier
            total_mb = max_val * multiplier
            
            return {"used_mb": used_mb, "total_mb": total_mb}

    async def _api_trigger_recharge(self) -> bool:
        """
        LÃ¶st Nachbuchung via API aus.
        """
        # The existing API URLs/schema have not been authenticated or verified.
        # Selecting the first DATA option can buy a paid tariff. Fail closed.
        return False

    # ==================== PLAYWRIGHT-METHODEN (FALLBACK) ====================

    async def _init_browser(self):
        """Initialisiert Playwright-Browser."""
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def _pw_login(self):
        """
        Login bei Lidl Connect via Playwright.
        """
        async def _login():
            await self.page.goto("https://kundenkonto.lidl-connect.de/mein-lidl-connect.html", timeout=30000)
            
            url = urlsplit(self.page.url)
            if url.scheme != "https" or url.hostname != "kundenkonto.lidl-connect.de":
                raise PermissionError("Lidl: Unexpected login origin")

            # Login-Form ausfÃ¼llen
            await self.page.fill(self.SELECTORS["username_input"], self.username)
            await self.page.fill(self.SELECTORS["password_input"], self.password)
            
            # Login absenden
            await self.page.click(self.SELECTORS["login_button"])
            await self.page.wait_for_load_state("networkidle")
            
            # Auf Erfolgsseite warten
            await self.page.wait_for_selector(self.SELECTORS["data_usage"], timeout=10000)
        
        # Login submission is not an idempotent read; do not resubmit on timeout.
        await _login()

    async def _pw_check_usage(self) -> Dict[str, float]:
        """
        PrÃ¼ft Datenvolumen via Playwright.
        """
        if self.page is None:
            await self._init_browser()
            await self._pw_login()

        async def _check():
            await self.page.goto("https://kundenkonto.lidl-connect.de/mein-lidl-connect.html", timeout=30000)
            
            # Datenvolumen extrahieren
            usage_text = await self.page.text_content(self.SELECTORS["data_value"])
            
            # Parse: "1,1 GB von 7,73 GB" oder "1126 MB von 7918 MB"
            match = re.search(r'([\d,\.]+)\s*(GB|MB)\s*von\s*([\d,\.]+)\s*(GB|MB)', usage_text, re.IGNORECASE)
            if not match:
                raise Exception("Lidl: Could not parse data volume")
            
            used_val = float(match.group(1).replace(',', '.'))
            used_unit = match.group(2).upper()
            total_val = float(match.group(3).replace(',', '.'))
            total_unit = match.group(4).upper()
            
            # In MB umrechnen
            multiplier_used = 1024 if used_unit == "GB" else 1
            multiplier_total = 1024 if total_unit == "GB" else 1
            
            return {
                "used_mb": used_val * multiplier_used,
                "total_mb": total_val * multiplier_total
            }
        
        usage = await self._exponential_backoff(_check)
        if not all(math.isfinite(usage[key]) and usage[key] >= 0 for key in ("used_mb", "total_mb")) or usage["used_mb"] > usage["total_mb"]:
            raise ValueError("Lidl: Invalid data volume")
        usage.update(await self._pw_refill_evidence())
        return usage

    async def _pw_refill_evidence(self):
        selectors = self.refill_selectors
        if not self.page or not all(selectors.get(key) for key in ("active_tariff", "refill_offer", "refill_button")):
            return unavailable("selectors_unconfigured")
        try:
            url = urlsplit(self.page.url)
            if url.scheme != "https" or url.hostname != "kundenkonto.lidl-connect.de":
                return unavailable("session_unverified")
            if await self.page.locator("input[type='password']").is_visible():
                return unavailable("session_unverified")
            logout = self.page.locator("a[href*='logout'], a[href*='logoff'], button:has-text('Abmelden'), button:has-text('Logout')")
            if await logout.count() != 1 or not await logout.is_visible():
                return unavailable("session_unverified")
            async def unique(root, selector):
                element = root.locator(selector)
                if await element.count() != 1 or not await element.is_visible():
                    raise ValueError("ambiguous_or_hidden_element")
                return element
            tariff = await unique(self.page, selectors["active_tariff"])
            offer = await unique(self.page, selectors["refill_offer"])
            button = await unique(offer, selectors["refill_button"])
            enabled = (await button.is_enabled() and await button.get_attribute("aria-disabled") != "true"
                       and await button.get_attribute("disabled") is None)
            return assess_refill(await tariff.inner_text(), await offer.inner_text(), await button.inner_text(), enabled)
        except Exception:
            return unavailable("offer_unverified")

    async def _pw_trigger_recharge(self) -> bool:
        """
        LÃ¶st Nachbuchung via Playwright aus.
        """
        evidence = await self._pw_refill_evidence()
        if not evidence["refill_eligible"] or not self.refill_selectors.get("refill_success"):
            return False
        # Never accept an old success notice as confirmation of this request.
        success = self.page.locator(self.refill_selectors["refill_success"])
        if await success.count() > 1 or await success.is_visible():
            return False
        if self.refill_mode == "needed":
            # Refresh usage immediately before acting; a previous poll may be stale.
            usage = await self._pw_check_usage()
            if not self.should_recharge_for_usage(usage):
                return False
        try:
            offer = self.page.locator(self.refill_selectors["refill_offer"])
            button = offer.locator(self.refill_selectors["refill_button"])
            await button.click(timeout=10000)
            await success.wait_for(state="visible", timeout=10000)
            text = " ".join((await success.inner_text()).split())
            url = urlsplit(self.page.url)
            quantities = re.findall(r"(?<![\d.,])([\d]+(?:[.,]\d+)?)\s*GB\b", text, re.I)
            if (url.scheme != "https" or url.hostname != "kundenkonto.lidl-connect.de"
                    or not quantities or any(q not in {"1", "1.0", "1,0", "1.00", "1,00"} for q in quantities)
                    or await success.count() != 1
                    or not re.search(r"(?<![\d.,])1(?:[.,]0+)?\s*GB\b", text, re.I)
                    or not re.search(r"\berfolgreich\b", text, re.I)
                    or not re.search(r"\b(?:nachgebucht|gebucht)\b", text, re.I)
                    or re.search(r"\b(?:nicht|fehlgeschlagen|Fehler)\b", text, re.I)):
                raise RechargeUnknownError("Lidl confirmation is not specific to a successful 1-GB refill")
            return True
        except Exception:
            # No retry, API fallback or second click after an uncertain side effect.
            raise RechargeUnknownError("Lidl browser booking outcome is unknown") from None

    # ==================== PUBLIC METHODS ====================

    async def check_usage(self) -> Dict[str, float]:
        """
        PrÃ¼ft Datenvolumen (API oder Playwright).
        """
        if self.use_api:
            try:
                return await self._api_check_usage()
            except Exception as e:
                print(f"Lidl API failed, falling back to Playwright: {e}")
                self.use_api = False  # Switch to Playwright
        
        # Fallback: Playwright
        return await self._pw_check_usage()

    def should_recharge_for_usage(self, usage: Dict[str, float]) -> bool:
        """Fail closed unless the provider check verified a free refill."""
        return bool(
            usage.get("refill_eligible") is True
            and usage.get("refill_type") == "FREE_UNLIMITED"
            and (self.refill_mode == "available" or self._remaining_below_threshold(usage))
        )

    def _remaining_below_threshold(self, usage):
        try:
            used, total = usage["used_mb"], usage["total_mb"]
            return (not isinstance(used, bool) and not isinstance(total, bool)
                    and math.isfinite(used) and math.isfinite(total)
                    and 0 <= used <= total and total - used <= self.threshold_mb)
        except (KeyError, TypeError, ValueError):
            return False

    async def trigger_recharge(self, recharge_id: Optional[str] = None) -> bool:
        """
        LÃ¶st Nachbuchung aus (API oder Playwright).
        """
        if self.dry_run or self.database is None or not recharge_id:
            return False
        records = self.database.get_unresolved_recharges(self.provider_name, self.username)
        if not any(record.recharge_id == recharge_id and record.status == "PENDING" for record in records):
            return False
        if self.use_api:
            # Never switch channels after a booking request with uncertain outcome.
            return await self._api_trigger_recharge()
        
        # Fallback: Playwright
        return await self._pw_trigger_recharge()

    async def close(self):
        """SchlieÃ§t Browser und Session."""
        if self.session and not self.session.closed:
            await self.session.close()
        
        if self.page:
            await self.page.close()
            self.page = None
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def run(self):
        """
        Override run() fÃ¼r Cleanup.
        """
        try:
            result = await super().run()
            return result
        finally:
            await self.close()
