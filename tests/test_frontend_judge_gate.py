"""Unit tests for the frontend-only judge PIN gate."""

from frontend.judge_gate import configured_pin_hash, hash_pin, verify_pin


def test_verify_pin_preserves_leading_zeroes() -> None:
    expected = hash_pin("012345")

    assert verify_pin("012345", expected) is True
    assert verify_pin("12345", expected) is False


def test_verify_pin_rejects_empty_or_malformed_configuration() -> None:
    assert verify_pin("012345", "") is False
    assert verify_pin("012345", "not-a-sha256") is False
    assert verify_pin("", hash_pin("012345")) is False


def test_configured_pin_hash_fails_closed_when_missing_or_invalid() -> None:
    assert configured_pin_hash({}) is None
    assert configured_pin_hash({"JUDGE_PIN_SHA256": 123456}) is None
    assert configured_pin_hash({"JUDGE_PIN_SHA256": "bad"}) is None


def test_configured_pin_hash_accepts_a_sha256_digest_without_exposing_pin() -> None:
    digest = hash_pin("012345")

    assert configured_pin_hash({"JUDGE_PIN_SHA256": digest.upper()}) == digest
