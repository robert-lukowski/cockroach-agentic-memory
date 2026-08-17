"""Live Amazon Bedrock adapter for embeddings, grounded generation, and privacy audit."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from incident_memory.errors import AdapterContractError, ExternalServiceError
from incident_memory.models import EMBEDDING_DIMENSIONS, IncidentEvidence

_SYSTEM_PROMPT = """You are an incident-response assistant. Use only the supplied prior-incident
evidence and clearly distinguish evidence from inference. Return concise plain text with a Diagnosis
heading followed by a short diagnosis, then a Recommended actions heading followed by a numbered
list of concrete diagnostic and remediation steps. Do not use Markdown tables, pipe-delimited rows,
HTML, or other wide formatting. Do not list or repeat incident IDs or incident numbers because the
application returns supporting evidence separately. Do not invent causes, commands, or observations.
If evidence is insufficient, say so."""

_PRIVACY_AUDIT_SYSTEM_PROMPT = """You are the Privacy Guard validation agent. You receive only text
that has already passed deterministic direct-identifier redaction. Do not reconstruct, infer, or
invent removed personal data. Decide only whether the sanitized text still appears to contain a
direct personal identifier such as an email address, telephone number, or explicitly labeled human
name. Placeholders such as [REDACTED_EMAIL], [REDACTED_PHONE], and [REDACTED_NAME] are safe and must
not trigger review. Return exactly one token: PASS or REVIEW_REQUIRED."""


class BedrockRuntimeGateway:
    """Calls approved Bedrock models through the native runtime APIs."""

    def __init__(
        self,
        *,
        region: str,
        embedding_model_id: str,
        generation_model_id: str,
        client: Any | None = None,
    ) -> None:
        self._region = region
        self._embedding_model_id = embedding_model_id
        self._generation_model_id = generation_model_id
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        return self._client

    def generate_embedding(self, text: str) -> Sequence[float]:
        body = json.dumps(
            {
                "inputText": text,
                "dimensions": EMBEDDING_DIMENSIONS,
                "normalize": True,
                "embeddingTypes": ["float"],
            }
        )
        try:
            response = self.client.invoke_model(
                modelId=self._embedding_model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            raw_body = response["body"].read()
            payload = json.loads(raw_body)
        except (
            BotoCoreError,
            ClientError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise ExternalServiceError("Bedrock embedding") from error

        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            raise AdapterContractError("Bedrock returned an invalid embedding response.")
        return embedding

    def generate_recommendation(
        self,
        *,
        symptoms: str,
        evidence: Sequence[IncidentEvidence],
    ) -> str:
        evidence_payload = [item.generation_context() for item in evidence]
        user_prompt = (
            "Current symptoms:\n"
            f"{symptoms}\n\n"
            "Retrieved prior-incident evidence (JSON):\n"
            f"{json.dumps(evidence_payload, ensure_ascii=False, separators=(',', ':'))}"
        )
        try:
            response = self.client.converse(
                modelId=self._generation_model_id,
                system=[{"text": _SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": 800, "temperature": 0.1},
            )
            blocks = response["output"]["message"]["content"]
        except (BotoCoreError, ClientError, KeyError, TypeError) as error:
            raise ExternalServiceError("Bedrock generation") from error

        if not isinstance(blocks, list):
            raise AdapterContractError("Bedrock returned an invalid generation response.")
        text_parts = [
            block["text"] for block in blocks if isinstance(block, dict) and "text" in block
        ]
        if not text_parts:
            raise AdapterContractError("Bedrock returned no recommendation text.")
        return "\n".join(text_parts)

    def audit_privacy(self, *, text: str, categories: tuple[str, ...]) -> str:
        """Validate already-redacted text without ever receiving the removed identifiers."""
        user_prompt = (
            "Deterministic redaction categories: "
            f"{', '.join(categories) if categories else 'none'}\n\n"
            "Sanitized incident text:\n"
            f"{text}"
        )
        try:
            response = self.client.converse(
                modelId=self._generation_model_id,
                system=[{"text": _PRIVACY_AUDIT_SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": 8, "temperature": 0.0},
            )
            blocks = response["output"]["message"]["content"]
        except (BotoCoreError, ClientError, KeyError, TypeError) as error:
            raise ExternalServiceError("Bedrock privacy audit") from error

        if not isinstance(blocks, list):
            raise AdapterContractError("Bedrock returned an invalid privacy audit response.")
        text_parts = [
            block["text"] for block in blocks if isinstance(block, dict) and "text" in block
        ]
        verdict = " ".join(text_parts).strip().upper()
        if verdict not in {"PASS", "REVIEW_REQUIRED"}:
            raise AdapterContractError("Bedrock returned an invalid privacy audit verdict.")
        return verdict
