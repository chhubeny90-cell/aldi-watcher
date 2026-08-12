"""
Lidl Connect Watcher Plugin.
Playwright (Headless Browser) für Lidl Connect.

⚠️ WICHTIG: CSS-Selektoren unten sind PLATZHALTER!
Diese müssen mit DevTools oder playwright codegen gegen die echte 
lidl-connect.de Seite ermittelt werden.

Beispiel für playwright codegen:
  playwright codegen https://www.lidl-connect.de/login

Typische Selektoren, die du ermitteln musst:
- Login-Form (form#... oder .login-form)
- Username-Input (input[name="username"] oder #username)
- Password-Input (input[name="password"] oder #password)
- Login-Button (button[type="submit"] oder .login-btn)
- Datenvolumen-Anzeige (div.data-usage, span.volume, etc.)
- Buchungs-Button (button.reload, .recharge-btn, etc.)
- Erfolgsmeldung (div.success, .alert-success, etc.)
"""

import asyncio
import re
from typing import Dict, Optional
from playwright.async_api import async_playwright, Browser, Page
from .base_watcher import BaseWatcher


class LidlConnectWatcher(BaseWatcher):
    """
    Watcher für Lidl Connect Prepaid-Daten.
    Nutzt Playwright für Browser-Automatisierung.
    """

    BASE_URL = "https://www.lidl-connect.de"
    LOGIN_URL = f"{BASE_URL}/login"
    OVERVIEW_URL = f"{BASE_URL}/konto/uebersicht"

    # ⚠️ PLATZHALTER - MIT DEVTOOLS ERMITTELN!
    SELECTORS = {
        "login_form": "form#loginForm",  # TODO: Ersetzen mit echtem Selector
        "username_input": "input#username",  # TODO: Ersetzen mit echtem Selector
        "password_input": "input#password",  # TODO: Ersetzen mit echtem Selector
        "login_button": "button[type='submit']",  # TODO: Ersetzen mit echtem Selector
        "data_usage": "div.data-usage > span.current",  # TODO: Ersetzen mit echtem Selector
        "recharge_button": "button.reload-data",  # TODO: Ersetzen mit echtem Selector
        "success_message": "div.success-message",  # TODO: Ersetzen mit echtem Selector
    }

    def __init__(self, username: str, password: str, threshold_mb: float, dry_run: bool = True):
        super().__init__(username, password, threshold_mb, dry_run)
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def _exponential_backoff(self, func, max_retries: int = 5, base_delay: float = 1.0):
        """
        Fhrt func mit exponentiellem Backoff aus.
        Fngt Timeouts/Captchas ab.
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

    async def _init_browser(self):
        """Initialisiert Playwright-Browser."""
        playwright = await async_playwright()
        self.browser = await playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def login(self):
        """
        Login bei Lidl Connect mit exponentiellem Backoff.
        """
        async def _login():
            await self.page.goto(self.LOGIN_URL, timeout=30000)
            
            # Login-Form ausfllen
            await self.page.fill(self.SELECTORS["username_input"], self.username)
            await self.page.fill(self.SELECTORS["password_input"], self.password)
            
            # Login absenden
            await self.page.click(self.SELECTORS["login_button"])
            await self.page.wait_for_load_state("networkidle")
            
            # Auf Erfolgsseite warten
            await self.page.wait_for_selector(self.SELECTORS["data_usage"], timeout=10000)
        
        await self._exponential_backoff(_login)

    async def check_usage(self) -> Dict[str, float]:
        """
        Prüft Datenvolumen bei Lidl Connect.
        """
        if self.page is None:
            await self._init_browser()
        
        async def _check():
            await self.page.goto(self.OVERVIEW_URL, timeout=30000)
            
            # Datenvolumen extrahieren
            usage_text = await self.page.text_content(self.SELECTORS["data_usage"])
            
            # Parse: "1234 MB von 5000 MB"
            match = re.search(r'(\d+\.?\d*)\s*MB\s*von\s*(\d+\.?\d*)\s*MB', usage_text)
            if not match:
                raise Exception("Lidl: Could not parse data volume")
            
            return {
                "used_mb": float(match.group(1)),
                "total_mb": float(match.group(2))
            }
        
        return await self._exponential_backoff(_check)

    async def trigger_recharge(self) -> bool:
        """
        Lst Lidl Connect Nachbuchung aus.
        """
        async def _recharge():
            # Buchungs-Button klicken
            await self.page.click(self.SELECTORS["recharge_button"], timeout=10000)
            await self.page.wait_for_load_state("networkidle")
            
            # Auf Besttigung warten
            await self.page.wait_for_selector(self.SELECTORS["success_message"], timeout=10000)
            return True
        
        try:
            await self._exponential_backoff(_recharge)
            return True
        except Exception:
            return False

    async def close(self):
        """Schliet Browser und Playwright."""
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()

    async def run(self):
        """
        Override run() für Browser-Cleanup.
        """
        try:
            result = await super().run()
            return result
        finally:
            await self.close()
