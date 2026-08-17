"""Unit tests for the frontend-only judge access-code gate."""

from frontend.judge_gate import (
    configured_access_hash,
    hash_access_code,
    verify_access_code,
)

_VALID_CODE = "0aBcDefGhijkLmnoPqrstUvwxYz_12345"


def test_verify_access_code_accepts_high_entropy_style_value_and_preserves_exact_text() -> None:
    expected = hash_access_code(_VALID_CODE)

    assert verify_access_code(_VALID_CODE, expected) is True
    assert verify_access_code(_VALID_CODE[1:], expected) is False


def test_verify_access_code_rejects_short_pin_even_when_hash_matches() -> None:
    short_pin = "012345"

    assert verify_access_code(short_pin, hash_access_code(short_pin)) is False


def test_verify_access_code_rejects_empty_or_malformed_configuration() -> None:
    assert verify_access_code(_VALID_CODE, "") is False
    assert verify_access_code(_VALID_CODE, "not-a-sha256") is False
    assert verify_access_code("", hash_access_code(_VALID_CODE)) is False


def test_configured_access_hash_fails_closed_when_missing_or_invalid() -> None:
    assert configured_access_hash({}) is None
    assert configured_access_hash({"JUDGE_ACCESS_CODE_SHA256": 123456}) is None
    assert configured_access_hash({"JUDGE_ACCESS_CODE_SHA256": "bad"}) is None


def test_configured_access_hash_accepts_sha256_digest_without_exposing_code() -> None:
    digest = hash_access_code(_VALID_CODE)

    assert configured_access_hash({"JUDGE_ACCESS_CODE_SHA256": digest.upper()}) == digest
