"""
Zentrales Konfigurations-Modul für aldi-watcher.
Liest .env-Variablen mit Fernet-Entschlsselung.
"""

import os
import math
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from .security import SecurityManager
from .lidl_refill import configured_selectors


class Config:
    """
    Zentrale Konfiguration für aldi-watcher.
    """

    def __init__(self, env_file: str = ".env"):
        load_dotenv(env_file)
        self.security = SecurityManager()
        
        # ALDI Talk Konfiguration
        self.aldi_user = self._get_credential("ALDI_USER")
        self.aldi_pass = self._get_credential("ALDI_PASS")
        self.threshold_aldi_mb = float(os.getenv("THRESHOLD_ALDI_MB", "500"))
        
        # Lidl Connect Konfiguration
        self.lidl_user = self._get_credential("LIDL_USER")
        self.lidl_pass = self._get_credential("LIDL_PASS")
        self.threshold_lidl_mb = float(os.getenv("THRESHOLD_LIDL_MB", "500"))
        
        self.lidl_use_api = self._get_bool("LIDL_USE_API", False)
        self.lidl_refill_mode = os.getenv("LIDL_REFILL_MODE", "available").strip()
        if self.lidl_refill_mode not in {"available", "needed"}:
            raise ValueError("LIDL_REFILL_MODE must be available or needed")
        self.lidl_refill_selectors = configured_selectors()

        # Betriebsmodi
        self.dry_run = self._get_bool("DRY_RUN", True)
        self.auto_book_enabled = self._get_bool("AUTO_BOOK_ENABLED", False)
        if not self.dry_run and not self.auto_book_enabled:
            raise ValueError("Live plugin mode requires AUTO_BOOK_ENABLED=true")
        self.poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
        self.db_path = os.getenv("DB_PATH", "aldi_watcher.db")
        if self.poll_interval <= 0:
            raise ValueError("POLL_INTERVAL_SECONDS must be positive")
        for value in (self.threshold_aldi_mb, self.threshold_lidl_mb):
            if not math.isfinite(value) or value < 0:
                raise ValueError("Volume thresholds must be finite and nonnegative")

    @staticmethod
    def _get_bool(key: str, default: bool) -> bool:
        value = os.getenv(key, str(default)).strip().lower()
        if value not in {"true", "false"}:
            raise ValueError(f"{key} must be true or false")
        return value == "true"

    def _get_credential(self, key: str) -> Optional[str]:
        """
        Ruft Credential ab: zuerst verschlsselt aus .env, dann Fallback unverschlsselt.
        """
        encrypted_value = os.getenv(f"{key}_ENC")
        if encrypted_value:
            try:
                return self.security.decrypt(encrypted_value)
            except Exception:
                raise ValueError(f"Cannot decrypt {key}_ENC") from None
        
        # Fallback auf unverschlsselte .env
        return os.getenv(key)

    def validate(self) -> bool:
        """
        Validiert die Konfiguration.
        Returns True wenn alle required Fields vorhanden sind.
        """
        required = [
            ("ALDI", self.aldi_user, self.aldi_pass),
            ("LIDL", self.lidl_user, self.lidl_pass)
        ]
        
        for provider, user, password in required:
            if not user or not password:
                print(f"Warning: {provider} credentials missing")
        
        return bool((self.aldi_user and self.aldi_pass) or 
                    (self.lidl_user and self.lidl_pass))
