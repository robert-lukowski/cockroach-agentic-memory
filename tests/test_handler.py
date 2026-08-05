"""Unit tests for API Gateway request and response handling."""

import base64
import json
import logging
from dataclasses import dataclass

from handler import create_lambda_handler, lambda_handler
from incident_memory.config import Settings
from incident_memory.errors import ExternalServiceError
from incident_memory.service import IncidentMemoryService
from tests.fakes import MockBedrockGateway, MockMcpIncidentRepository
from tests.test_models import valid_servicenow_payload


@dataclass
class FakeContext:
    aws_request_id: str = "test-request-id"


def api_event(method: str, path: str, body: object | None = None) -> dict[str, object]:
    return {
        "resource": path,
        "path": path,
        "httpMethod": method,
        "requestContext": {"requestId": "gateway-request-id"},
        "body": None if body is None else json.dumps(body),
        "isBase64Encoded": False,
    }


def test_health_returns_only_process_and_configuration_status() -> None:
    settings = Settings.from_environment(
        {
            "SERVICE_NAME": "incident-memory-test",
            "APP_MODE": "test",
            "REPOSITORY_BACKEND": "mock-mcp",
            "BEDROCK_EMBEDDING_MODEL_ID": "embedding-model",
            "BEDROCK_GENERATION_MODEL_ID": "generation-model",
            "EMBEDDING_DIMENSIONS": "1024",
            "IGNORED_SECRET": "must-not-appear",
        }
    )
    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=MockBedrockGateway(),
            repository=MockMcpIncidentRepository(),
        ),
        settings=settings,
    )

    response = handler(api_event("GET", "/health"), FakeContext())
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["status"] == "ok"
    assert body["configuration"]["embedding_model_configured"] is True
    assert body["configuration"]["repository_configured"] is True
    assert "embedding-model" not in response["body"]
    assert "mock-mcp" not in response["body"]
    assert "must-not-appear" not in response["body"]


def test_create_incident_route_returns_created_response() -> None:
    repository = MockMcpIncidentRepository()
    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=MockBedrockGateway(),
            repository=repository,
        ),
        settings=Settings.from_environment({}),
    )
    payload = {
        "scope": "hackathon-demo",
        "service": "payments-api",
        "environment": "production",
        "title": "Connection pool exhaustion",
        "symptoms": "Checkout latency rose.",
        "root_cause": "Concurrency exceeded the pool.",
        "resolution": "Bound concurrency and raised the pool limit.",
    }

    response = handler(api_event("POST", "/incidents", payload), FakeContext())
    body = json.loads(response["body"])

    assert response["statusCode"] == 201
    assert body["incident_id"] == str(repository.saved[0].incident_id)


def test_investigation_route_returns_repository_evidence(evidence) -> None:
    repository = MockMcpIncidentRepository(evidence=[evidence])
    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=MockBedrockGateway(recommendation="Inspect connection saturation."),
            repository=repository,
        ),
        settings=Settings.from_environment({}),
    )

    response = handler(
        api_event(
            "POST",
            "/investigations",
            {
                "scope": "hackathon-demo",
                "symptoms": "Database waits are rising.",
            },
        ),
        FakeContext(),
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["recommendation"] == "Inspect connection saturation."
    assert body["supporting_incident_ids"] == [str(evidence.incident.incident_id)]


def test_invalid_json_returns_safe_validation_error() -> None:
    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=MockBedrockGateway(),
            repository=MockMcpIncidentRepository(),
        ),
        settings=Settings.from_environment({}),
    )
    event = api_event("POST", "/incidents")
    event["body"] = "{not-json"

    response = handler(event, FakeContext())
    body = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["request_id"] == "test-request-id"


def test_invalid_base64_body_returns_validation_error() -> None:
    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=MockBedrockGateway(),
            repository=MockMcpIncidentRepository(),
        ),
        settings=Settings.from_environment({}),
    )
    event = api_event("POST", "/incidents")
    event["body"] = "%%%"
    event["isBase64Encoded"] = True

    response = handler(event, FakeContext())

    assert response["statusCode"] == 400


def test_valid_base64_body_is_decoded() -> None:
    repository = MockMcpIncidentRepository()
    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=MockBedrockGateway(),
            repository=repository,
        ),
        settings=Settings.from_environment({}),
    )
    payload = {
        "scope": "hackathon-demo",
        "service": "payments-api",
        "environment": "production",
        "title": "Connection pool exhaustion",
        "symptoms": "Checkout latency rose.",
        "root_cause": "Concurrency exceeded the pool.",
        "resolution": "Bound concurrency and raised the pool limit.",
    }
    event = api_event("POST", "/incidents")
    event["body"] = base64.b64encode(json.dumps(payload).encode()).decode()
    event["isBase64Encoded"] = True

    response = handler(event, FakeContext())

    assert response["statusCode"] == 201


def test_default_handler_fails_closed_without_live_adapters() -> None:
    payload = {
        "scope": "hackathon-demo",
        "service": "payments-api",
        "environment": "production",
        "title": "Connection pool exhaustion",
        "symptoms": "Checkout latency rose.",
        "root_cause": "Concurrency exceeded the pool.",
        "resolution": "Bound concurrency and raised the pool limit.",
    }

    response = lambda_handler(api_event("POST", "/incidents", payload), FakeContext())
    body = json.loads(response["body"])

    assert response["statusCode"] == 503
    assert body["error"]["code"] == "dependency_unavailable"


def test_unknown_route_returns_not_found() -> None:
    response = lambda_handler(api_event("GET", "/unknown"), FakeContext())

    assert response["statusCode"] == 404


def test_servicenow_analyze_reuses_investigation_without_storing(evidence) -> None:
    repository = MockMcpIncidentRepository(evidence=[evidence])
    bedrock = MockBedrockGateway(recommendation="Inspect connection saturation.")
    handler = create_lambda_handler(
        service=IncidentMemoryService(bedrock=bedrock, repository=repository),
        settings=Settings.from_environment({"SERVICENOW_MEMORY_SCOPE": "hackathon-demo"}),
    )

    response = handler(
        api_event("POST", "/servicenow/analyze", valid_servicenow_payload()),
        FakeContext(),
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body == {
        "recommendation": "Inspect connection saturation.",
        "supporting_incident_ids": [str(evidence.incident.incident_id)],
    }
    assert repository.saved == []
    assert repository.search_calls[0]["scope"] == "hackathon-demo"
    assert bedrock.generation_calls


def test_servicenow_analyze_rejects_oversized_body() -> None:
    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=MockBedrockGateway(),
            repository=MockMcpIncidentRepository(),
        ),
        settings=Settings.from_environment({}),
    )
    event = api_event("POST", "/servicenow/analyze")
    event["body"] = json.dumps({"description": "x" * (33 * 1024)})

    response = handler(event, FakeContext())
    body = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert body["error"]["code"] == "validation_error"
    assert "32768" in body["error"]["message"]


def test_servicenow_analyze_returns_safe_mcp_failure(caplog) -> None:
    class FailingRepository(MockMcpIncidentRepository):
        def find_similar(self, **kwargs):
            raise ExternalServiceError("CockroachDB Managed MCP")

    sensitive_description = "PRIVATE-DESCRIPTION-MUST-NOT-BE-LOGGED"
    payload = valid_servicenow_payload()
    payload["description"] = sensitive_description
    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=MockBedrockGateway(),
            repository=FailingRepository(),
        ),
        settings=Settings.from_environment({}),
    )

    with caplog.at_level(logging.INFO):
        response = handler(api_event("POST", "/servicenow/analyze", payload), FakeContext())
    body = json.loads(response["body"])

    assert response["statusCode"] == 502
    assert body["error"]["code"] == "external_service_error"
    assert sensitive_description not in caplog.text
    assert sensitive_description not in response["body"]


def test_servicenow_analyze_returns_safe_bedrock_failure() -> None:
    class FailingBedrock(MockBedrockGateway):
        def generate_embedding(self, text: str):
            raise ExternalServiceError("Amazon Bedrock")

    handler = create_lambda_handler(
        service=IncidentMemoryService(
            bedrock=FailingBedrock(),
            repository=MockMcpIncidentRepository(),
        ),
        settings=Settings.from_environment({}),
    )

    response = handler(
        api_event("POST", "/servicenow/analyze", valid_servicenow_payload()),
        FakeContext(),
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 502
    assert body["error"]["code"] == "external_service_error"
