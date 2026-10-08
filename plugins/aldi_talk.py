r"""
ALDI Talk Watcher Plugin.
HTTP/API-basierte Implementierung (aus watcher.py extrahiert).

DOM-Selektoren & Requests (aus watcher.py):
- Login: POST /konto/login
- Overview: GET /konto/uebersicht
- Datenvolumen-Parsing: Regex '(\d+\.?\d*)\s*MB\s*von\s*(\d+\.?\d*)\s*MB'
- Recharge: disabled until an authorized real provider flow is verified.
"""

import re
import aiohttp
from typing import Dict, Optional
from .base_watcher import BaseWatcher


class AldiTalkWatcher(BaseWatcher):
    """
    Watcher für ALDI Talk Prepaid-Daten.
    Nutzt HTTP/API-Zugriff auf alditalk.de.
    """

    BASE_URL = "https://www.alditalk.de"
    LOGIN_URL = f"{BASE_URL}/konto/login"
    OVERVIEW_URL = f"{BASE_URL}/konto/uebersicht"
    RECHARGE_URL = f"{BASE_URL}/konto/datenvolumen/nachbuchen"

    def __init__(self, username: str, password: str, threshold_mb: float, dry_run: bool = True, database=None):
        super().__init__(username, password, threshold_mb, dry_run, database)
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Erstellt oder returniert existierende Session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def login(self) -> str:
        """
        Login bei ALDI Talk.
        Returns Session-Cookie für weitere Requests.
        """
        session = await self._get_session()
        
        # Login-Request
        async with session.post(
            self.LOGIN_URL,
            data={"username": self.username, "password": self.password},
            allow_redirects=True
        ) as response:
            if response.status != 200:
                raise Exception(f"ALDI Login failed: {response.status}")
            
            # Session-Cookie extrahieren
            session_cookie = response.cookies.get("PHPSESSID")
            if not session_cookie:
                raise Exception("ALDI Login: No session cookie")
            
            return session_cookie.value

    async def check_usage(self) -> Dict[str, float]:
        """
        Prüft Datenvolumen bei ALDI Talk.
        """
        session = await self._get_session()
        
        async with session.get(
            self.OVERVIEW_URL,
            headers={"Cookie": f"PHPSESSID={await self.login()}"}
        ) as response:
            html = await response.text()
            
            # Datenvolumen parsen (Regex aus watcher.py)
            match = re.search(r'(\d+\.?\d*)\s*MB\s*von\s*(\d+\.?\d*)\s*MB', html)
            if not match:
                raise Exception("ALDI: Could not parse data volume")
            
            used_mb = float(match.group(1))
            total_mb = float(match.group(2))
            
            return {"used_mb": used_mb, "total_mb": total_mb}

    def should_recharge_for_usage(self, usage: Dict[str, float]) -> bool:
        """Fail closed unless the provider check verified a free refill."""
        return bool(
            usage.get("refill_eligible") is True
            and usage.get("refill_type") == "FREE_UNLIMITED"
        )

    async def trigger_recharge(self, recharge_id: Optional[str] = None) -> bool:
        """Do not mutate an account through the unverified legacy endpoint."""
        raise NotImplementedError(
            "ALDI refill requires an authorized and verified provider flow"
        )

    async def close(self):
        """Schliet die HTTP-Session."""
        if self.session and not self.session.closed:
            await self.session.close()
