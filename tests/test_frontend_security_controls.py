"""Tests for the static, repository-verified security scorecard."""

import re

from frontend.security_controls import VERIFIED_SECURITY_CONTROLS


def test_verified_security_scorecard_contains_supported_controls() -> None:
    expected = {
        "GitHub OIDC": "Enabled",
        "Static AWS credentials": "0",
        "AWS credential model": "Temporary",
        "Secrets storage": "AWS Secrets Manager",
        "IAM model": "Least privilege",
        "ServiceNow API": "API key protected",
        "CockroachDB memory access": "Managed MCP",
        "Transport": "HTTPS",
        "Source secrets": "0 exposed",
    }

    assert {control.name: control.status for control in VERIFIED_SECURITY_CONTROLS} == expected
    assert all(control.description for control in VERIFIED_SECURITY_CONTROLS)


def test_security_scorecard_contains_no_resource_or_credential_values() -> None:
    rendered_text = "\n".join(
        (control.name + "\n" + control.status + "\n" + control.description)
        for control in VERIFIED_SECURITY_CONTROLS
    )

    assert "arn:" not in rendered_text.lower()
    assert "https://" not in rendered_text.lower()
    assert re.search(r"\b\d{12}\b", rendered_text) is None
    assert re.search(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", rendered_text) is None
    assert re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", rendered_text) is None
