"""Validate deployment target without exposing phone numbers in errors."""

import re
from core.aldi_http_login import phone_identifier, LoginError


def require_refill_target(account, expected, required_suffix):
    """Require full identity equality; a suffix is an extra deployment check only."""
    if not isinstance(required_suffix, str) or not re.fullmatch(r"[0-9]{4}", required_suffix):
        raise ValueError("target_suffix_invalid")
    if not expected:
        raise ValueError("expected_target_missing")
    try:
        actual = phone_identifier(account)
        wanted = phone_identifier(expected)
    except (LoginError, TypeError):
        raise ValueError("target_account_invalid") from None
    if actual != wanted:
        raise ValueError("target_account_mismatch")
    if not wanted.endswith(required_suffix):
        raise ValueError("target_profile_mismatch")
