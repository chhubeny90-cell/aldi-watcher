"""
Security-Manager mit Fernet-Verschlsselung für Credentials.
Untersttzt Fernet (.secret.key) mit .env-Fallback.
"""

import os
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet


class SecurityManager:
    """
    Verwaltet Credential-Verschlsselung.
    - Primr: Fernet mit .secret.key
    - Fallback: .env (unverschlsselt)
    """

    def __init__(self, key_file: str = ".secret.key"):
        self.key_file = Path(key_file)
        self.fernet: Optional[Fernet] = None
        self._load_or_create_key()

    def _load_or_create_key(self):
        """Ldt existierenden Key oder erstellt neuen."""
        if self.key_file.exists():
            with open(self.key_file, "rb") as f:
                key = f.read()
            self.fernet = Fernet(key)
        else:
            # Neuen Key generieren und speichern
            key = Fernet.generate_key()
            with open(self.key_file, "wb") as f:
                f.write(key)
            self.fernet = Fernet(key)
            # .gitignore-Eintrag sicherstellen
            self._ensure_gitignore()

    def _ensure_gitignore(self):
        """Stellt sicher, dass .secret.key in .gitignore steht."""
        gitignore = Path(".gitignore")
        content = ""
        if gitignore.exists():
            with open(gitignore, "r") as f:
                content = f.read()
        
        if ".secret.key" not in content:
            with open(gitignore, "a") as f:
                f.write("\n# Encryption key\n.secret.key\n")

    def encrypt(self, plaintext: str) -> str:
        """Verschlsselt einen String mit Fernet."""
        if self.fernet is None:
            raise RuntimeError("Fernet nicht initialisiert")
        return self.fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Entschlsselt einen String mit Fernet."""
        if self.fernet is None:
            raise RuntimeError("Fernet nicht initialisiert")
        return self.fernet.decrypt(ciphertext.encode()).decode()

    @staticmethod
    def get_env_credential(key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Ruft Credential aus .env (Fallback-Modus).
        """
        return os.getenv(key, default)
