"""Narrow HTTPS client for the existing ServiceNow analysis endpoint."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_TIMEOUT_SECONDS = 45.0
TRANSIENT_RETRY_DELAY_SECONDS = 1.0
_TRANSIENT_RETRY_STATUSES = frozenset({502, 503})
_TIMEOUT_NAMES = (
    "AGENTIC_MEMORY_REQUEST_TIMEOUT_SECONDS",
    "AGENTIC_MEMORY_REQUEST_TIMEOUT",
    "AGENTIC_MEMORY_API_TIMEOUT",
)


class FrontendConfigurationError(RuntimeError):
    """Safe configuration failure containing variable names but no values."""


class ApiClientError(RuntimeError):
    """Sanitized backend failure without response bodies or credentials."""

    def __init__(self, category: str, *, status: int | None = None) -> None:
        self.category = category
        self.status = status
        suffix = f" (HTTP {status})" if status is not None else ""
        super().__init__(f"{category}{suffix}")


@dataclass(frozen=True, slots=True)
class FrontendConfig:
    endpoint: str
    api_key: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


@dataclass(frozen=True, slots=True)
class ApiCallResult:
    payload: dict[str, Any]
    round_trip_ms: float
    transient_retry_occurred: bool


class HttpTransport(Protocol):
    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> HttpResponse:
        """Send one HTTPS POST with an explicit timeout."""


class UrllibTransport:
    def __init__(self) -> None:
        self._tls_context = ssl.create_default_context()

    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=self._tls_context,
            ) as response:
                return HttpResponse(status=response.status, body=response.read())
        except urllib.error.HTTPError as error:
            return HttpResponse(status=error.code, body=b"")
        except (TimeoutError, urllib.error.URLError) as error:
            raise ApiClientError("The analysis request timed out or could not connect.") from error


def _setting(
    name: str,
    *,
    environment: Mapping[str, str],
    secrets: Mapping[str, object],
) -> str | None:
    environment_value = environment.get(name)
    if environment_value:
        return environment_value
    secret_value = secrets.get(name)
    return secret_value if isinstance(secret_value, str) and secret_value else None


def load_config(
    *,
    environment: Mapping[str, str] | None = None,
    secrets: Mapping[str, object] | None = None,
) -> FrontendConfig:
    values = os.environ if environment is None else environment
    protected = {} if secrets is None else secrets
    endpoint = _setting(
        "AGENTIC_MEMORY_API_ENDPOINT",
        environment=values,
        secrets=protected,
    )
    api_key = _setting(
        "AGENTIC_MEMORY_API_KEY",
        environment=values,
        secrets=protected,
    )
    missing = [
        name
        for name, value in (
            ("AGENTIC_MEMORY_API_ENDPOINT", endpoint),
            ("AGENTIC_MEMORY_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        raise FrontendConfigurationError(
            "Missing frontend configuration: " + ", ".join(missing) + "."
        )

    parsed = urllib.parse.urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise FrontendConfigurationError(
            "AGENTIC_MEMORY_API_ENDPOINT must be a credential-free HTTPS URL."
        )

    timeout_value = next(
        (
            value
            for name in _TIMEOUT_NAMES
            if (value := _setting(name, environment=values, secrets=protected)) is not None
        ),
        str(DEFAULT_TIMEOUT_SECONDS),
    )
    try:
        timeout_seconds = float(timeout_value)
    except (TypeError, ValueError) as error:
        raise FrontendConfigurationError("The frontend request timeout must be numeric.") from error
    if not 1.0 <= timeout_seconds <= 120.0:
        raise FrontendConfigurationError(
            "The frontend request timeout must be between 1 and 120 seconds."
        )
    return FrontendConfig(
        endpoint=endpoint.rstrip("/"),
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


class AgenticMemoryApiClient:
    """POST-only client that never exposes the configured API key in errors."""

    def __init__(
        self,
        config: FrontendConfig,
        *,
        transport: HttpTransport | None = None,
        clock=time.perf_counter,
        sleeper=time.sleep,
    ) -> None:
        self._config = config
        self._transport = transport or UrllibTransport()
        self._clock = clock
        self._sleeper = sleeper

    def analyze(self, payload: Mapping[str, str]) -> ApiCallResult:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-api-key": self._config.api_key,
        }
        started = self._clock()
        response = self._transport.request(
            url=self._config.endpoint,
            headers=headers,
            body=body,
            timeout=self._config.timeout_seconds,
        )
        transient_retry_occurred = response.status in _TRANSIENT_RETRY_STATUSES
        if transient_retry_occurred:
            self._sleeper(TRANSIENT_RETRY_DELAY_SECONDS)
            response = self._transport.request(
                url=self._config.endpoint,
                headers=headers,
                body=body,
                timeout=self._config.timeout_seconds,
            )
        elapsed_ms = (self._clock() - started) * 1_000
        if not 200 <= response.status < 300:
            raise ApiClientError(
                "The backend rejected the analysis request.",
                status=response.status,
            )
        if not response.body:
            raise ApiClientError("The backend returned an empty response.")
        try:
            decoded = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiClientError("The backend returned invalid JSON.") from error
        if not isinstance(decoded, dict):
            raise ApiClientError("The backend returned an invalid response object.")
        return ApiCallResult(
            payload=decoded,
            round_trip_ms=elapsed_ms,
            transient_retry_occurred=transient_retry_occurred,
        )
