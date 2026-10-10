"""Encrypt a private account manifest locally; password/key never enter logs."""
import argparse
import getpass
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="Private JSON containing numbers and policies; never commit it")
    parser.add_argument("--output", default="aldi-accounts.enc")
    args = parser.parse_args()
    try:
        from cryptography.fernet import Fernet
        from core.aldi_accounts import validate_accounts
        payload = json.loads(Path(args.manifest).read_text())
        # Use the user's existing shared password without echoing it. It is not
        # inferred from a browser session or copied from another account.
        password = getpass.getpass("Gemeinsames ALDI-Passwort: ")
        for account in payload["accounts"]:
            account["password"] = password
        validate_accounts(payload)
        key = os.getenv("CREDENTIAL_ENCRYPTION_KEY") or getpass.getpass("Vorhandener Verschluesselungsschluessel: ")
        token = Fernet(key.strip().encode()).encrypt(json.dumps(payload).encode())
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(token)
        print("Encrypted account file created; upload its contents as ALDI_ACCOUNTS_ENC.")
        return 0
    except Exception:
        print("Account encryption failed; no credential details are printed.")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
