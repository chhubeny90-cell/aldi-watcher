"""Resolve credentials without changing the process environment or logging values."""
import os
from pathlib import Path
from dotenv import dotenv_values
from .security import SecurityManager

CREDENTIAL_NAMES = ("ALDI_USER", "ALDI_PASS", "LIDL_USER", "LIDL_PASS")


def validated(name, value):
    placeholders = {'your-aldi-password', 'your-lidl-password', 'your-password',
                    'your_aldi_password', 'your_lidl_password', 'changeme', 'change_me',
                    'your-aldi-passwort', 'your-lidl-passwort', 'your-passwort',
                    'your_aldi_passwort', 'your_lidl_passwort'}
    if name.endswith('_PASS') and value and value.casefold() in placeholders:
        raise ValueError(f"Placeholder credential for {name}")
    return value or None


def get_credential(name, env_file=None, security=None, environ=None):
    if name not in CREDENTIAL_NAMES:
        raise ValueError("Unsupported credential name")
    environ = os.environ if environ is None else environ
    values = dotenv_values(env_file or environ.get("CREDENTIAL_ENV_FILE") or ".env")
    # Empty GitHub secret variables do not shadow the encrypted fallback.
    source = environ if any(environ.get(name + suffix) for suffix in ("_ENC", "_FILE", "")) else values
    encrypted = source.get(name + "_ENC")
    file_path = source.get(name + "_FILE")
    if encrypted and file_path:
        raise ValueError(f"Conflicting credential sources for {name}")
    if encrypted:
        try:
            value = (security or SecurityManager()).decrypt(encrypted)
        except Exception:
            raise ValueError(f"Cannot decrypt {name}_ENC") from None
        return validated(name, value)
    if file_path:
        try:
            path = Path(file_path)
            if not path.is_absolute() or path.is_symlink():
                raise ValueError()
            if os.name == "posix" and path.stat().st_mode & 0o077:
                raise ValueError()
            value = path.read_text().rstrip("\r\n")
            if not value:
                raise ValueError()
            return validated(name, value)
        except (OSError, ValueError):
            raise ValueError(f"Cannot read protected {name}_FILE") from None
    return validated(name, source.get(name))
