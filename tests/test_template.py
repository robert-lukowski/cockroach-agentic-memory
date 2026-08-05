"""Infrastructure contract tests for route-specific authorization."""

from pathlib import Path


def _template() -> str:
    return Path("template.yaml").read_text(encoding="utf-8")


def test_existing_routes_keep_iam_as_the_default_authorizer() -> None:
    template = _template()

    assert "DefaultAuthorizer: AWS_IAM" in template
    boundaries = {
        "Health": "CreateIncident",
        "CreateIncident": "Investigate",
        "Investigate": "ServiceNowAnalyze",
    }
    for event_name, next_event_name in boundaries.items():
        event_block = template.split(f"        {event_name}:\n", maxsplit=1)[1].split(
            f"        {next_event_name}:\n", maxsplit=1
        )[0]
        assert "Authorizer: NONE" not in event_block
        assert "ApiKeyRequired: true" not in event_block


def test_servicenow_route_requires_generated_api_key_and_usage_plan() -> None:
    template = _template()
    event_block = template.split("        ServiceNowAnalyze:\n", maxsplit=1)[1].split(
        "    Metadata:", maxsplit=1
    )[0]
    key_block = template.split("  ServiceNowApiKey:\n", maxsplit=1)[1].split(
        "  ServiceNowUsagePlan:\n", maxsplit=1
    )[0]

    assert "Path: /servicenow/analyze" in event_block
    assert "Authorizer: NONE" in event_block
    assert "ApiKeyRequired: true" in event_block
    assert "\n      Value:" not in key_block
    assert "BurstLimit: 2" in template
    assert "RateLimit: 1" in template
    assert "Limit: 100" in template
    assert "Period: DAY" in template
