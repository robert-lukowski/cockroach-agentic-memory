"""Secret retrieval that never logs or exposes secret values."""

from __future__ import annotations

from threading import Lock
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from incident_memory.errors import AdapterContractError, ExternalServiceError


class SecretsManagerApiKeyProvider:
    """Retrieve and cache one plaintext Managed MCP API key."""

    def __init__(
        self,
        *,
        secret_arn: str,
        region: str,
        client: Any | None = None,
    ) -> None:
        self._secret_arn = secret_arn
        self._region = region
        self._client = client
        self._cached_value: str | None = None
        self._lock = Lock()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = boto3.client("secretsmanager", region_name=self._region)
        return self._client

    def get_api_key(self) -> str:
        if self._cached_value is not None:
            return self._cached_value
        with self._lock:
            if self._cached_value is not None:
                return self._cached_value
            try:
                response = self.client.get_secret_value(SecretId=self._secret_arn)
                secret_value = response["SecretString"]
            except (BotoCoreError, ClientError, KeyError, TypeError) as error:
                raise ExternalServiceError("Secrets Manager") from error
            if not isinstance(secret_value, str) or not secret_value.strip():
                raise AdapterContractError("The MCP credential secret is empty or invalid.")
            self._cached_value = secret_value.strip()
            return self._cached_value
