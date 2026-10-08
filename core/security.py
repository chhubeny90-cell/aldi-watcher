"""Fernet credentials; a missing decryption key is never silently replaced."""
import os
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet


class SecurityManager:
    def __init__(self, key_file: str = ".secret.key"):
        self.key_file = Path(os.getenv("CREDENTIAL_KEY_FILE") or key_file)
        self.fernet: Optional[Fernet] = None

    def _load_key(self):
        if self.fernet is not None:
            return self.fernet
        key = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
        try:
            if not key and self.key_file.is_symlink():
                raise ValueError("Credential key symlink not allowed")
            raw = key.strip().encode() if key else self.key_file.read_bytes().strip()
            if not key and os.name == "posix" and self.key_file.stat().st_mode & 0o077:
                raise ValueError("Credential key permissions must be owner-only")
            self.fernet = Fernet(raw)
        except (OSError, ValueError):
            raise ValueError("Credential encryption key missing, invalid or insecure") from None
        return self.fernet

    def encrypt(self, plaintext: str) -> str:
        return self._load_key().encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._load_key().decrypt(ciphertext.encode()).decode()

    @staticmethod
    def get_env_credential(key: str, default: Optional[str] = None) -> Optional[str]:
        return os.getenv(key, default)
