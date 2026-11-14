"""GSTIN format and checksum validation.

A GSTIN has 15 characters: 2-digit state code, 10-character PAN, entity number (1-9, A-Z),
the letter Z, and a check character computed with a base-36 Luhn-style algorithm.
"""

from __future__ import annotations

import re

CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
# State / UT codes 01-38, plus 97 (other territory) and 99 (centre jurisdiction).
VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}


def normalise(gstin: str | None) -> str | None:
    if gstin is None:
        return None
    cleaned = re.sub(r"[\s\-]", "", gstin).upper()
    return cleaned or None


def checksum_char(first14: str) -> str:
    """Check character for the first 14 characters of a GSTIN."""
    if len(first14) != 14:
        raise ValueError("need exactly 14 characters")
    total = 0
    for i, ch in enumerate(first14):
        value = CHARSET.index(ch)
        product = value * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return CHARSET[(36 - total % 36) % 36]


def validate(gstin: str | None) -> str | None:
    """Return None if the GSTIN is valid, else a short reason."""
    g = normalise(gstin)
    if not g:
        return "missing"
    if len(g) != 15:
        return f"length {len(g)} (expected 15)"
    if not GSTIN_RE.match(g):
        return "bad format"
    if g[:2] not in VALID_STATE_CODES:
        return f"unknown state code {g[:2]}"
    expected = checksum_char(g[:14])
    if g[14] != expected:
        return f"checksum mismatch (expected {expected})"
    return None


def is_valid(gstin: str | None) -> bool:
    return validate(gstin) is None


def state_code(gstin: str | None) -> str | None:
    """State code if the first two characters look like one, even when the checksum fails."""
    g = normalise(gstin)
    if g and len(g) >= 2 and g[:2] in VALID_STATE_CODES:
        return g[:2]
    return None
