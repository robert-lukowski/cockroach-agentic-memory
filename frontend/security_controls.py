"""Static security controls verified from repository-owned project configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SecurityControl:
    name: str
    status: str
    description: str


VERIFIED_SECURITY_CONTROLS = (
    SecurityControl(
        name="Pre-AI Privacy Boundary",
        status="Enforced",
        description=(
            "Configured direct identifiers are redacted before Titan embeddings, durable "
            "operational memory, or the Bedrock-powered Investigator; the secondary privacy "
            "reviewer receives sanitized text only."
        ),
    ),
    SecurityControl(
        name="GitHub OIDC",
        status="Enabled",
        description=(
            "GitHub Actions uses OpenID Connect to obtain temporary AWS credentials without "
            "storing static AWS access keys."
        ),
    ),
    SecurityControl(
        name="Static AWS credentials",
        status="0",
        description=(
            "No long-lived AWS access key is required by the GitHub automation flow."
        ),
    ),
    SecurityControl(
        name="AWS credential model",
        status="Temporary",
        description="Short-lived role credentials are issued through AWS STS.",
    ),
    SecurityControl(
        name="Secrets storage",
        status="AWS Secrets Manager",
        description="Service integration credentials are stored outside source code.",
    ),
    SecurityControl(
        name="IAM model",
        status="Least privilege",
        description=(
            "Automation roles are scoped to the permissions required by the integration."
        ),
    ),
    SecurityControl(
        name="ServiceNow API",
        status="API key protected",
        description=(
            "The analysis endpoint uses a dedicated API Gateway key and throttled usage plan."
        ),
    ),
    SecurityControl(
        name="CockroachDB memory access",
        status="Managed MCP",
        description="Operational memory is accessed through CockroachDB Managed MCP.",
    ),
    SecurityControl(
        name="Transport",
        status="HTTPS",
        description="External service communication uses encrypted HTTPS endpoints.",
    ),
    SecurityControl(
        name="Source secrets",
        status="0 exposed",
        description=(
            "No real credentials are committed to the repository or rendered in the frontend."
        ),
    ),
)
