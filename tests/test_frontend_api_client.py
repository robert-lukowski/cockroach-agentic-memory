"""Tests for safe frontend configuration and HTTP handling."""

from __future__ import annotations

import json

import pytest

from frontend.api_client import (
    TRANSIENT_RETRY_DELAY_SECONDS,
    AgenticMemoryApiClient,
    ApiClientError,
    FrontendConfig,
    FrontendConfigurationError,
    HttpResponse,
    load_config,
)

ENDPOINT = "https://example.execute-api.eu-central-1.amazonaws.com/v1/servicenow/analyze"


class FakeTransport:
    def __init__(self, response: HttpResponse | list[HttpResponse]) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses[len(self.calls) - 1]


def config(api_key: str = "private-demo-key") -> FrontendConfig:
    return FrontendConfig(endpoint=ENDPOINT, api_key=api_key, timeout_seconds=30.0)


def test_loads_environment_before_streamlit_secrets() -> None:
    loaded = load_config(
        environment={
            "AGENTIC_MEMORY_API_ENDPOINT": ENDPOINT,
            "AGENTIC_MEMORY_API_KEY": "environment-key",
            "AGENTIC_MEMORY_REQUEST_TIMEOUT_SECONDS": "22",
        },
        secrets={
            "AGENTIC_MEMORY_API_ENDPOINT": "https://ignored.example/analyze",
            "AGENTIC_MEMORY_API_KEY": "ignored-key",
        },
    )

    assert loaded.endpoint == ENDPOINT
    assert loaded.api_key == "environment-key"
    assert loaded.timeout_seconds == 22.0


def test_missing_configuration_fails_without_exposing_available_value() -> None:
    with pytest.raises(FrontendConfigurationError) as captured:
        load_config(environment={"AGENTIC_MEMORY_API_KEY": "private-demo-key"})

    assert "AGENTIC_MEMORY_API_ENDPOINT" in str(captured.value)
    assert "private-demo-key" not in str(captured.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test/analyze",
        "https://user:password@example.test/analyze",
        "https://example.test/analyze?key=value",
    ],
)
def test_rejects_unsafe_endpoint(endpoint: str) -> None:
    with pytest.raises(FrontendConfigurationError, match="credential-free HTTPS"):
        load_config(
            environment={
                "AGENTIC_MEMORY_API_ENDPOINT": endpoint,
                "AGENTIC_MEMORY_API_KEY": "private-demo-key",
            }
        )


def test_posts_json_and_reports_measured_round_trip() -> None:
    transport = FakeTransport(
        HttpResponse(
            status=200,
            body=json.dumps({"recommendation": "Use the retrieved evidence."}).encode(),
        )
    )
    ticks = iter((10.0, 10.25))
    client = AgenticMemoryApiClient(config(), transport=transport, clock=lambda: next(ticks))

    result = client.analyze({"number": "INC9000003"})

    assert result.payload["recommendation"] == "Use the retrieved evidence."
    assert result.round_trip_ms == 250.0
    assert result.transient_retry_occurred is False
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["timeout"] == 30.0
    assert call["headers"]["x-api-key"] == "private-demo-key"
    assert json.loads(call["body"])["number"] == "INC9000003"


@pytest.mark.parametrize("transient_status", [502, 503])
def test_retries_one_transient_response_and_returns_success(transient_status: int) -> None:
    success = HttpResponse(
        status=200,
        body=json.dumps({"recommendation": "Use the retrieved evidence."}).encode(),
    )
    transport = FakeTransport(
        [HttpResponse(status=transient_status, body=b"provider detail"), success]
    )
    sleep_calls: list[float] = []
    ticks = iter((10.0, 11.25))
    client = AgenticMemoryApiClient(
        config(),
        transport=transport,
        clock=lambda: next(ticks),
        sleeper=sleep_calls.append,
    )

    result = client.analyze({"number": "INC9000003"})

    assert result.payload["recommendation"] == "Use the retrieved evidence."
    assert result.round_trip_ms == 1_250.0
    assert result.transient_retry_occurred is True
    assert len(transport.calls) == 2
    assert transport.calls[0] == transport.calls[1]
    assert sleep_calls == [TRANSIENT_RETRY_DELAY_SECONDS]


@pytest.mark.parametrize("transient_status", [502, 503])
def test_second_transient_failure_is_sanitized_without_third_attempt(
    transient_status: int,
) -> None:
    transport = FakeTransport(
        [
            HttpResponse(status=transient_status, body=b"first provider detail"),
            HttpResponse(status=transient_status, body=b"second provider detail"),
        ]
    )
    sleep_calls: list[float] = []
    client = AgenticMemoryApiClient(
        config(),
        transport=transport,
        sleeper=sleep_calls.append,
    )

    with pytest.raises(ApiClientError, match=f"HTTP {transient_status}") as captured:
        client.analyze({"number": "INC9000003"})

    assert len(transport.calls) == 2
    assert sleep_calls == [TRANSIENT_RETRY_DELAY_SECONDS]
    assert "provider detail" not in str(captured.value)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 504])
def test_non_retryable_status_makes_one_request(status: int) -> None:
    transport = FakeTransport(HttpResponse(status=status, body=b"provider detail"))
    sleep_calls: list[float] = []
    client = AgenticMemoryApiClient(
        config(),
        transport=transport,
        sleeper=sleep_calls.append,
    )

    with pytest.raises(ApiClientError, match=f"HTTP {status}"):
        client.analyze({"number": "INC9000003"})

    assert len(transport.calls) == 1
    assert sleep_calls == []


def test_invalid_json_does_not_retry() -> None:
    transport = FakeTransport(HttpResponse(status=200, body=b"not-json"))
    sleep_calls: list[float] = []
    client = AgenticMemoryApiClient(
        config(),
        transport=transport,
        sleeper=sleep_calls.append,
    )

    with pytest.raises(ApiClientError, match="invalid JSON"):
        client.analyze({"number": "INC9000003"})

    assert len(transport.calls) == 1
    assert sleep_calls == []


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (HttpResponse(status=401, body=b"sensitive provider body"), "HTTP 401"),
        (HttpResponse(status=200, body=b""), "empty response"),
        (HttpResponse(status=200, body=b"not-json"), "invalid JSON"),
        (HttpResponse(status=200, body=b"[]"), "invalid response object"),
    ],
)
def test_backend_failures_are_sanitized(response: HttpResponse, message: str) -> None:
    client = AgenticMemoryApiClient(config(), transport=FakeTransport(response))

    with pytest.raises(ApiClientError, match=message) as captured:
        client.analyze({"number": "INC9000003"})

    error = str(captured.value)
    assert "private-demo-key" not in error
    assert "sensitive provider body" not in error
