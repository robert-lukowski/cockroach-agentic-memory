"""Unit tests for the live Bedrock adapter with a fake SDK client."""

from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError

from incident_memory.adapters.bedrock import BedrockRuntimeGateway
from incident_memory.errors import AdapterContractError, ExternalServiceError
from incident_memory.models import EMBEDDING_DIMENSIONS


class FakeBody:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


class FakeBedrockClient:
    def __init__(self) -> None:
        self.invoke_response: object = {"body": FakeBody({"embedding": [0.5] * 1024})}
        self.converse_response: object = {
            "output": {"message": {"content": [{"text": "Use the prior remediation."}]}}
        }
        self.invoke_calls: list[dict[str, object]] = []
        self.converse_calls: list[dict[str, object]] = []

    def invoke_model(self, **kwargs):
        self.invoke_calls.append(kwargs)
        if isinstance(self.invoke_response, Exception):
            raise self.invoke_response
        return self.invoke_response

    def converse(self, **kwargs):
        self.converse_calls.append(kwargs)
        if isinstance(self.converse_response, Exception):
            raise self.converse_response
        return self.converse_response


def gateway(client: FakeBedrockClient) -> BedrockRuntimeGateway:
    return BedrockRuntimeGateway(
        region="eu-central-1",
        embedding_model_id="amazon.titan-embed-text-v2:0",
        generation_model_id="openai.gpt-oss-20b-1:0",
        client=client,
    )


def test_generates_normalized_1024_dimension_embedding() -> None:
    client = FakeBedrockClient()

    result = gateway(client).generate_embedding("database latency")

    assert len(result) == EMBEDDING_DIMENSIONS
    request = json.loads(client.invoke_calls[0]["body"])
    assert request == {
        "inputText": "database latency",
        "dimensions": 1024,
        "normalize": True,
        "embeddingTypes": ["float"],
    }


def test_generates_recommendation_from_supplied_evidence(evidence) -> None:
    client = FakeBedrockClient()

    result = gateway(client).generate_recommendation(
        symptoms="Database waits are rising.",
        evidence=[evidence],
    )

    assert result == "Use the prior remediation."
    call = client.converse_calls[0]
    prompt = call["messages"][0]["content"][0]["text"]
    system_prompt = call["system"][0]["text"]
    assert str(evidence.incident.incident_id) not in prompt
    assert "Database waits are rising." in prompt
    assert "Do not use Markdown tables" in system_prompt
    assert "numbered" in system_prompt
    assert "Do not list or repeat incident IDs" in system_prompt
    assert call["inferenceConfig"]["temperature"] == 0.1


def test_rejects_invalid_embedding_response() -> None:
    client = FakeBedrockClient()
    client.invoke_response = {"body": FakeBody({"not_embedding": []})}

    with pytest.raises(AdapterContractError, match="invalid embedding"):
        gateway(client).generate_embedding("latency")


def test_redacts_bedrock_client_error() -> None:
    client = FakeBedrockClient()
    client.invoke_response = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "sensitive-provider-detail"}},
        "InvokeModel",
    )

    with pytest.raises(ExternalServiceError) as captured:
        gateway(client).generate_embedding("latency")

    assert "sensitive-provider-detail" not in str(captured.value)


def test_rejects_generation_without_text() -> None:
    client = FakeBedrockClient()
    client.converse_response = {"output": {"message": {"content": [{"image": {}}]}}}

    with pytest.raises(AdapterContractError, match="no recommendation"):
        gateway(client).generate_recommendation(symptoms="latency", evidence=[])


def test_rejects_invalid_generation_content_shape() -> None:
    client = FakeBedrockClient()
    client.converse_response = {"output": {"message": {"content": "not-a-list"}}}

    with pytest.raises(AdapterContractError, match="invalid generation"):
        gateway(client).generate_recommendation(symptoms="latency", evidence=[])
