"""Small, frontend-only gate for judge-triggered live investigations."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping

JUDGE_ACCESS_HASH_SECRET = "JUDGE_ACCESS_CODE_SHA256"
ACCESS_CODE_MIN_LENGTH = 32
ACCESS_CODE_MAX_LENGTH = 128
_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
_ACCESS_CODE_PATTERN = re.compile(
    rf"[A-Za-z0-9_-]{{{ACCESS_CODE_MIN_LENGTH},{ACCESS_CODE_MAX_LENGTH}}}"
)


def hash_access_code(access_code: str) -> str:
    """Return the SHA-256 digest of the exact access-code string."""
    return hashlib.sha256(access_code.encode("utf-8")).hexdigest()


def configured_access_hash(secrets: Mapping[str, object]) -> str | None:
    """Return a normalized configured digest, or None when the gate is not configured."""
    value = secrets.get(JUDGE_ACCESS_HASH_SECRET)
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if _HASH_PATTERN.fullmatch(candidate) is None:
        return None
    return candidate.lower()


def verify_access_code(access_code: str, expected_hash: str) -> bool:
    """Validate a high-entropy judge access code against its configured digest.

    The public gate deliberately rejects short PIN-style credentials. Deployment documentation
    generates a random URL-safe value with ``secrets.token_urlsafe(24)``, which produces a
    32-character access code. This avoids relying on per-session attempt counters that can be
    bypassed by opening a new Streamlit session.
    """
    if not isinstance(access_code, str):
        return False
    if _ACCESS_CODE_PATTERN.fullmatch(access_code) is None:
        return False

    normalized_hash = expected_hash.strip().lower()
    if _HASH_PATTERN.fullmatch(normalized_hash) is None:
        return False
    return hmac.compare_digest(hash_access_code(access_code), normalized_hash)
