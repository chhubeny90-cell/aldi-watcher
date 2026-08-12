"""
Lidl Connect Watcher Plugin.

HYBRID-ANSATZ:
- PrimÃ¤r: API-Zugriff (schneller, stabiler, kein Browser-Overhead)
- Fallback: Playwright (falls API nicht verfÃ¼gbar)

API-Endpoints (reverse-engineered):
- Login: POST https://api.lidl-connect.de/api/authenticate
- Usage: GET https://api.lidl-connect.de/api/consumption
- Tariffs: GET https://api.lidl-connect.de/api/tariff-options
- Recharge: POST https://api.lidl-connect.de/api/tariff-option/book

API-Response-Format (Consumption):
{
  "consumptions": [
    {
      "type": "DATA",
      "consumed": 1.1,
      "left": 6.63,
      "max": 7.73,
      "unit": "GB",
      "expiresInSec": 1247851
    }
  ]
}

⚠️ WICHTIG: API kann sich Ãndern. Bei Fehlern auf Playwright-Fallback umstellen
oder Selector via playwright codegen aktualisieren:
  playwright codegen https://kundenkonto.lidl-connect.de/mein-lidl-connect.html
"""

import asyncio
import aiohttp
import re
from typing import Dict, Optional
from playwright.async_api import async_playwright, Browser, Page
from .base_watcher import BaseWatcher


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

    # Playwright-Selektoren (Fallback, falls API nicht geht)
    # Quelle: https://kundenkonto.lidl-connect.de/mein-lidl-connect.html
    SELECTORS = {
        "username_input": "input[type='tel']",  # Rufnummer-Input
        "password_input": "input[type='password']",
        "login_button": "button[type='submit']",
        "data_usage": "div.consumption-tile",  # Haupt-Datenkachel
        "data_value": "span.consumption-value",  # Verbrauchswert
        "recharge_button": "button[data-testid='book-tariff']",  # Nachbuchung
        "success_message": "div.alert-success",  # Erfolgsmeldung
    }

    def __init__(self, username: str, password: str, threshold_mb: float, dry_run: bool = True, use_api: bool = True):
        super().__init__(username, password, threshold_mb, dry_run)
        self.use_api = use_api  # True = API, False = Playwright
        self.session: Optional[aiohttp.ClientSession] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.auth_token: Optional[str] = None

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
        session = await self._get_api_session()
        
        # VerfÃ¼gbare Tarifs abrufen
        async with session.get(
            self.API_TARIFFS,
            headers={"Authorization": f"Bearer {self.auth_token}"}
        ) as response:
            if response.status != 200:
                return False
            
            tariffs = await response.json()
            
            # Passenden Tarif finden (z.B. "Data S", "Data M", etc.)
            # Hier: Erster verfÃ¼gbarer Data-Tarif
            tariff_id = None
            for tariff in tariffs.get("tariffOptions", []):
                if "DATA" in tariff.get("type", ""):
                    tariff_id = tariff.get("id")
                    break
            
            if not tariff_id:
                return False
            
            # Buchung auslÃ¶sen
            async with session.post(
                self.API_BOOK,
                json={"tariffOptionId": tariff_id},
                headers={"Authorization": f"Bearer {self.auth_token}"}
            ) as response:
                return response.status in [200, 201]

    # ==================== PLAYWRIGHT-METHODEN (FALLBACK) ====================

    async def _init_browser(self):
        """Initialisiert Playwright-Browser."""
        playwright = await async_playwright()
        self.browser = await playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def _pw_login(self):
        """
        Login bei Lidl Connect via Playwright.
        """
        async def _login():
            await self.page.goto("https://kundenkonto.lidl-connect.de/mein-lidl-connect.html", timeout=30000)
            
            # Login-Form ausfÃ¼llen
            await self.page.fill(self.SELECTORS["username_input"], self.username)
            await self.page.fill(self.SELECTORS["password_input"], self.password)
            
            # Login absenden
            await self.page.click(self.SELECTORS["login_button"])
            await self.page.wait_for_load_state("networkidle")
            
            # Auf Erfolgsseite warten
            await self.page.wait_for_selector(self.SELECTORS["data_usage"], timeout=10000)
        
        await self._exponential_backoff(_login)

    async def _pw_check_usage(self) -> Dict[str, float]:
        """
        PrÃ¼ft Datenvolumen via Playwright.
        """
        if self.page is None:
            await self._init_browser()
        
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
        
        return await self._exponential_backoff(_check)

    async def _pw_trigger_recharge(self) -> bool:
        """
        LÃ¶st Nachbuchung via Playwright aus.
        """
        async def _recharge():
            # Buchungs-Button klicken
            await self.page.click(self.SELECTORS["recharge_button"], timeout=10000)
            await self.page.wait_for_load_state("networkidle")
            
            # Auf BestÃ¤tigung warten
            await self.page.wait_for_selector(self.SELECTORS["success_message"], timeout=10000)
            return True
        
        try:
            await self._exponential_backoff(_recharge)
            return True
        except Exception:
            return False

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

    async def trigger_recharge(self) -> bool:
        """
        LÃ¶st Nachbuchung aus (API oder Playwright).
        """
        if self.use_api:
            try:
                return await self._api_trigger_recharge()
            except Exception as e:
                print(f"Lidl API recharge failed, falling back to Playwright: {e}")
                self.use_api = False
        
        # Fallback: Playwright
        return await self._pw_trigger_recharge()

    async def close(self):
        """SchlieÃ§t Browser und Session."""
        if self.session and not self.session.closed:
            await self.session.close()
        
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()

    async def run(self):
        """
        Override run() fÃ¼r Cleanup.
        """
        try:
            result = await super().run()
            return result
        finally:
            await self.close()
