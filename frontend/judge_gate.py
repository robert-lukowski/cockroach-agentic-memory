"""Small, frontend-only gate for judge-triggered live investigations."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping

JUDGE_PIN_HASH_SECRET = "JUDGE_PIN_SHA256"
_PIN_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


def hash_pin(pin: str) -> str:
    """Return the SHA-256 digest of the exact PIN string.

    The PIN is intentionally not normalized so leading zeroes and other characters remain
    significant.
    """
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def configured_pin_hash(secrets: Mapping[str, object]) -> str | None:
    """Return a normalized configured digest, or None when the gate is not safely configured."""
    value = secrets.get(JUDGE_PIN_HASH_SECRET)
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if _PIN_HASH_PATTERN.fullmatch(candidate) is None:
        return None
    return candidate.lower()


def verify_pin(pin: str, expected_hash: str) -> bool:
    """Compare the exact PIN against a configured SHA-256 digest in constant time."""
    if not isinstance(pin, str) or not pin:
        return False
    normalized_hash = expected_hash.strip().lower()
    if _PIN_HASH_PATTERN.fullmatch(normalized_hash) is None:
        return False
    return hmac.compare_digest(hash_pin(pin), normalized_hash)
