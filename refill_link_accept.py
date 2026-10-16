"""Validate and atomically reserve signed refill requests. No provider action.

Call only on an explicit POST from the configured client, never on link GET or
email preview. The caller must keep the SQLite database on persistent storage.
An accepted request is not proof that ALDI booked any data.
"""
import base64
import hashlib
import hmac
import json
import re
import sqlite3
import time


def accept(token, *, key, profile, database, now=None):
    """Reserve once; reject invalid/expired/replayed requests without logging tokens."""
    now = int(time.time() if now is None else now)
    if not isinstance(key, str) or len(key.encode()) < 32:
        raise ValueError('invalid_signing_key')
    if not isinstance(token, str) or len(token) > 4096:
        raise ValueError('invalid_token')
    parts = token.split('.')
    if len(parts) != 2 or any(not re.fullmatch(r'[A-Za-z0-9_-]+', p) for p in parts):
        raise ValueError('invalid_token')
    encoded, signature = parts
    expected = base64.urlsafe_b64encode(hmac.new(key.encode(), encoded.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    if not hmac.compare_digest(signature, expected):
        raise ValueError('invalid_signature')
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    except (ValueError, UnicodeError):
        raise ValueError('invalid_payload') from None
    if not isinstance(payload, dict):
        raise ValueError('invalid_payload')
    issued, expires = payload.get('iat'), payload.get('exp')
    if type(issued) is not int or type(expires) is not int:
        raise ValueError('invalid_time')
    if not issued <= now < expires or not 60 <= expires - issued <= 3600:
        raise ValueError('expired_or_invalid_time')
    nonce = payload.get('nonce')
    if (type(payload.get('v')) is not int or payload['v'] != 1
            or payload.get('action') != 'request_refill'
            or payload.get('profile') != profile
            or not isinstance(nonce, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{24}', nonce)):
        raise ValueError('invalid_request')
    request_id = hashlib.sha256((profile + ':' + nonce).encode()).hexdigest()
    with sqlite3.connect(database, timeout=10) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS refill_requests (request_id TEXT PRIMARY KEY, accepted_at INTEGER NOT NULL, status TEXT NOT NULL)')
        try:
            connection.execute('INSERT INTO refill_requests VALUES (?, ?, ?)', (request_id, now, 'pending'))
        except sqlite3.IntegrityError:
            raise ValueError('already_accepted') from None
    return {'request_id': request_id, 'status': 'pending', 'provider_action': False}
