"""AWS Lambda proxy handler for the incident-memory API."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from incident_memory.bootstrap import build_service
from incident_memory.config import Settings
from incident_memory.errors import ApplicationError, ValidationError
from incident_memory.models import (
    IncidentCreateRequest,
    InvestigationRequest,
    ServiceNowAnalyzeRequest,
)
from incident_memory.service import IncidentMemoryService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

LambdaResponse = dict[str, Any]
_SERVICENOW_MAX_BODY_BYTES = 32 * 1024


def _response(status_code: int, payload: Mapping[str, Any]) -> LambdaResponse:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
    }


def _request_id(event: Mapping[str, Any], context: object) -> str:
    context_id = getattr(context, "aws_request_id", None)
    request_context = event.get("requestContext", {})
    gateway_id = request_context.get("requestId") if isinstance(request_context, dict) else None
    return str(context_id or gateway_id or "local")


def _route(event: Mapping[str, Any]) -> tuple[str, str]:
    request_context = event.get("requestContext", {})
    http_context = request_context.get("http", {}) if isinstance(request_context, dict) else {}
    method = event.get("httpMethod") or http_context.get("method") or ""
    path = event.get("resource") or event.get("rawPath") or event.get("path") or ""
    return str(method).upper(), str(path)


def _json_body(event: Mapping[str, Any], *, maximum_bytes: int | None = None) -> object:
    raw_body = event.get("body")
    if isinstance(raw_body, dict):
        if maximum_bytes is not None:
            body_size = len(
                json.dumps(raw_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            )
            if body_size > maximum_bytes:
                raise ValidationError(f"Request body must not exceed {maximum_bytes} bytes.")
        return raw_body
    if not isinstance(raw_body, str) or not raw_body.strip():
        raise ValidationError("Request body must contain JSON.")
    if event.get("isBase64Encoded"):
        try:
            body_bytes = base64.b64decode(raw_body, validate=True)
            if maximum_bytes is not None and len(body_bytes) > maximum_bytes:
                raise ValidationError(f"Request body must not exceed {maximum_bytes} bytes.")
            raw_body = body_bytes.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as error:
            raise ValidationError("Request body is not valid base64-encoded UTF-8.") from error
    elif maximum_bytes is not None and len(raw_body.encode("utf-8")) > maximum_bytes:
        raise ValidationError(f"Request body must not exceed {maximum_bytes} bytes.")
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise ValidationError("Request body contains invalid JSON.") from error


def create_lambda_handler(
    *,
    service: IncidentMemoryService,
    settings: Settings,
) -> Callable[[Mapping[str, Any], object], LambdaResponse]:
    """Create a Lambda handler with explicit, testable dependencies."""

    def handle(event: Mapping[str, Any], context: object) -> LambdaResponse:
        request_id = _request_id(event, context)
        method, path = _route(event)
        try:
            if (method, path) == ("GET", "/health"):
                return _response(200, settings.health_payload())
            if (method, path) == ("POST", "/incidents"):
                request = IncidentCreateRequest.from_payload(_json_body(event))
                result = service.create_incident(request)
                return _response(201 if result.status == "created" else 200, result.as_dict())
            if (method, path) == ("POST", "/investigations"):
                request = InvestigationRequest.from_payload(_json_body(event))
                result = service.investigate(request)
                return _response(200, result.as_dict())
            if (method, path) == ("POST", "/servicenow/analyze"):
                servicenow_request = ServiceNowAnalyzeRequest.from_payload(
                    _json_body(event, maximum_bytes=_SERVICENOW_MAX_BODY_BYTES)
                )
                result = service.investigate(
                    servicenow_request.as_investigation(scope=settings.servicenow_memory_scope)
                )
                return _response(200, result.as_servicenow_dict())
            return _response(
                404,
                {
                    "error": {
                        "code": "not_found",
                        "message": "Route not found.",
                        "request_id": request_id,
                    }
                },
            )
        except ApplicationError as error:
            logger.info(
                "request_failed",
                extra={"request_id": request_id, "error_code": error.code},
            )
            error_payload: dict[str, Any] = {
                "code": error.code,
                "message": error.message,
                "request_id": request_id,
            }
            if error.details:
                error_payload["details"] = error.details
            return _response(error.status_code, {"error": error_payload})
        except Exception:
            logger.exception("unexpected_request_failure", extra={"request_id": request_id})
            return _response(
                500,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "An unexpected error occurred.",
                        "request_id": request_id,
                    }
                },
            )

    return handle


_settings = Settings.from_environment()
_service = build_service(_settings)
lambda_handler = create_lambda_handler(service=_service, settings=_settings)
