"""Tests for the Bedrock Privacy Guard second-opinion call."""

from __future__ import annotations

import pytest

from incident_memory.adapters.bedrock import BedrockRuntimeGateway
from incident_memory.errors import AdapterContractError


class FakeBedrockClient:
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[dict[str, object]] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"content": [{"text": self.verdict}]}}}


def gateway(client: FakeBedrockClient) -> BedrockRuntimeGateway:
    return BedrockRuntimeGateway(
        region="eu-central-1",
        embedding_model_id="amazon.titan-embed-text-v2:0",
        generation_model_id="openai.gpt-oss-20b-1:0",
        client=client,
    )


def test_privacy_agent_receives_only_sanitized_text_and_uses_low_variance_config() -> None:
    client = FakeBedrockClient("PASS")
    sanitized = "Name: [REDACTED_NAME]\nEmail: [REDACTED_EMAIL]"

    verdict = gateway(client).audit_privacy(
        text=sanitized,
        categories=("email", "name"),
    )

    assert verdict == "PASS"
    call = client.calls[0]
    prompt = call["messages"][0]["content"][0]["text"]
    system_prompt = call["system"][0]["text"]
    assert sanitized in prompt
    assert "alex.morgan@example.invalid" not in prompt
    assert "Return exactly one token" in system_prompt
    assert call["inferenceConfig"] == {"maxTokens": 8, "temperature": 0.0}


def test_privacy_agent_rejects_unexpected_output() -> None:
    client = FakeBedrockClient("MAYBE")

    with pytest.raises(AdapterContractError, match="invalid privacy audit verdict"):
        gateway(client).audit_privacy(
            text="Email: [REDACTED_EMAIL]",
            categories=("email",),
        )
