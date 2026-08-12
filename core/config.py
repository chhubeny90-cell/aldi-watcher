"""
Zentrales Konfigurations-Modul für aldi-watcher.
Liest .env-Variablen mit Fernet-Entschlsselung.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from .security import SecurityManager


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
        
        # Betriebsmodi
        self.dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
        self.poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "3600"))
        self.db_path = os.getenv("DB_PATH", "aldi_watcher.db")

    def _get_credential(self, key: str) -> Optional[str]:
        """
        Ruft Credential ab: zuerst verschlsselt aus .env, dann Fallback unverschlsselt.
        """
        encrypted_value = os.getenv(f"{key}_ENC")
        if encrypted_value:
            try:
                return self.security.decrypt(encrypted_value)
            except Exception:
                pass
        
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
