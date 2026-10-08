"""Encrypt .env credentials in place without printing numbers, passwords or keys."""
import argparse
import os
import re
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from .credentials import CREDENTIAL_NAMES


def protect(source, destination, key_file):
    source, destination, key_file = map(Path, (source, destination, key_file))
    values = dotenv_values(source)
    # A key must live outside the tracked configuration, and never be overwritten.
    if key_file.resolve() in {source.resolve(), destination.resolve()}:
        raise ValueError('key_path_conflicts_with_configuration')
    if key_file.is_symlink():
        raise ValueError('key_symlink_not_allowed')
    if key_file.exists():
        if os.name == 'posix' and key_file.stat().st_mode & 0o077:
            raise ValueError('key_permissions_not_private')
        key = key_file.read_bytes().strip()
    else:
        key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = Fernet.generate_key()
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(key)
    cipher = Fernet(key)
    protected = {}
    for name in CREDENTIAL_NAMES:
        existing = values.get(name + '_ENC')
        plain = values.get(name)
        if existing and plain:
            raise ValueError('ambiguous_plain_and_encrypted_credentials')
        if existing:
            cipher.decrypt(existing.encode())  # Verify before replacing any file.
            protected[name] = existing
        elif plain:
            protected[name] = cipher.encrypt(plain.encode()).decode()
    names = {name + suffix for name in CREDENTIAL_NAMES for suffix in ('', '_ENC')}
    comment = '# Key: CREDENTIAL_ENCRYPTION_KEY secret or owner-only CREDENTIAL_KEY_FILE.'
    lines = []
    for line in source.read_text().splitlines():
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
        if line != comment and not (match and match[1] in names):
            lines.append(line)
    lines += [comment]
    lines += [name + '_ENC=' + token for name, token in protected.items()]
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.protected-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write('\n'.join(lines) + '\n')
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(protected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='.env')
    parser.add_argument('--output', default='.env')
    parser.add_argument('--key-file', required=True)
    args = parser.parse_args(argv)
    try:
        count = protect(args.source, args.output, args.key_file)
    except Exception:
        parser.exit(1, 'Credential protection failed; configuration was not replaced.\n')
    print(f'Protected {count} credential fields; key is stored separately.')


if __name__ == '__main__':
    main()
