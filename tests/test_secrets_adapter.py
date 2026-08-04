"""Unit tests for redacted and cached Secrets Manager access."""

import pytest
from botocore.exceptions import ClientError

from incident_memory.adapters.secrets import SecretsManagerApiKeyProvider
from incident_memory.errors import AdapterContractError, ExternalServiceError


class FakeSecretsClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def get_secret_value(self, **kwargs):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def provider(client: FakeSecretsClient) -> SecretsManagerApiKeyProvider:
    return SecretsManagerApiKeyProvider(
        secret_arn="arn:aws:secretsmanager:eu-central-1:123456789012:secret:mcp",
        region="eu-central-1",
        client=client,
    )


def test_retrieves_and_caches_api_key() -> None:
    client = FakeSecretsClient({"SecretString": "test-api-key"})
    api_key_provider = provider(client)

    assert api_key_provider.get_api_key() == "test-api-key"
    assert api_key_provider.get_api_key() == "test-api-key"
    assert client.calls == 1


def test_invalidation_reloads_rotated_api_key() -> None:
    client = FakeSecretsClient({"SecretString": "first-test-api-key"})
    api_key_provider = provider(client)
    assert api_key_provider.get_api_key() == "first-test-api-key"
    client.result = {"SecretString": "rotated-test-api-key"}

    api_key_provider.invalidate()

    assert api_key_provider.get_api_key() == "rotated-test-api-key"
    assert client.calls == 2


def test_rejects_empty_secret() -> None:
    with pytest.raises(AdapterContractError, match="empty"):
        provider(FakeSecretsClient({"SecretString": "  "})).get_api_key()


def test_redacts_secrets_manager_error() -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "sensitive-secret-detail"}},
        "GetSecretValue",
    )

    with pytest.raises(ExternalServiceError) as captured:
        provider(FakeSecretsClient(error)).get_api_key()

    assert "sensitive-secret-detail" not in str(captured.value)
