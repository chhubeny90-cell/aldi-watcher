"""Strict, non-logging identity comparison for Lidl account evidence."""
import re


def normalize_phone(value):
    if not isinstance(value, str) or re.search(r"[^\d+\s()/.-]", value):
        return None
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0049"):
        digits = "0" + digits[4:]
    elif digits.startswith("49"):
        digits = "0" + digits[2:]
    return digits if re.fullmatch(r"01[0-9]{9,10}", digits) else None


def matches_account(text, expected):
    """Require exactly one complete number and an independently valid target."""
    target = normalize_phone(expected)
    if not target or not isinstance(text, str):
        return False
    matches = re.findall(r"(?<![\d+])(?:\+49|0049|0)\s*1(?:[\s()/.-]*\d){8,11}(?!\d)", text)
    return [normalize_phone(match) for match in matches] == [target]
