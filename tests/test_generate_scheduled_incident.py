"""Tests for the scheduled synthetic ServiceNow incident generator."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from scripts.generate_scheduled_incident import (
    DEFAULT_DATASET,
    SCHEDULED_MARKER,
    CallerConfiguration,
    ScheduledIncidentClient,
    ServiceNowCredentials,
    build_scheduled_payload,
    caller_configuration_from_values,
    generate_incident,
    load_active_scenarios,
    parse_secret_json,
    select_scenario,
)
from scripts.seed_servicenow_incidents import (
    ConfigurationError,
    HttpResponse,
    ServiceNowError,
)

WORKFLOW = Path(".github/workflows/generate-demo-incident.yml")
OIDC_TEMPLATE = Path("infrastructure/github-actions-oidc.yaml")
FIXED_CORRELATION_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
CREATED_SYS_ID = "abcdefabcdefabcdefabcdefabcdefab"
ELIGIBLE_CALLER_ID = "11111111111111111111111111111111"
SECOND_CALLER_ID = "22222222222222222222222222222222"
EXCLUDED_CALLER_ID = "33333333333333333333333333333333"


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _created_response(status: int = 201) -> HttpResponse:
    body = json.dumps(
        {"result": {"number": "INC9012345", "sys_id": CREATED_SYS_ID}}
    ).encode()
    return HttpResponse(status, body)


def _user_response(records: list[dict[str, object]], status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps({"result": records}).encode())


def _credentials() -> ServiceNowCredentials:
    return ServiceNowCredentials(
        instance_url="https://fictional.service-now.example",
        username="scheduled-demo-user",
        password="fictional-password",
    )


def test_workflow_yaml_and_triggers_are_valid() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert isinstance(workflow, dict)
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["on"]["schedule"] == [{"cron": "0 */6 * * *"}]
    assert workflow["permissions"] == {"id-token": "write", "contents": "read"}


def test_workflow_uses_oidc_variables_without_static_credentials() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "aws-actions/configure-aws-credentials@v6.1.2" in text
    assert "${{ vars.AWS_OIDC_ROLE_ARN }}" in text
    assert "${{ vars.SERVICENOW_SECRET_ID }}" in text
    assert "eu-central-1" in text
    assert "secretsmanager get-secret-value" in text
    assert "SERVICENOW_CALLER_MODE: random" in text
    assert "aws-access-key-id" not in text.lower()
    assert "aws-secret-access-key" not in text.lower()
    assert "${{ secrets." not in text


def test_oidc_template_is_repository_branch_and_secret_scoped() -> None:
    template = yaml.load(OIDC_TEMPLATE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    role = template["Resources"]["ScheduledDemoIncidentRole"]["Properties"]
    trust = role["AssumeRolePolicyDocument"]["Statement"]
    permissions = role["Policies"][0]["PolicyDocument"]["Statement"]

    assert len(trust) == 1
    assert trust[0]["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert trust[0]["Condition"]["StringEquals"] == {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": (
            "repo:robert-lukowski@207513888/"
            "cockroach-agentic-memory@1322917399:ref:refs/heads/main"
        ),
    }
    assert permissions == [
        {
            "Effect": "Allow",
            "Action": "secretsmanager:GetSecretValue",
            "Resource": "ServiceNowSecretArn",
        }
    ]


def test_missing_or_invalid_secret_configuration_fails_safely() -> None:
    sensitive = "fictional-password-that-must-not-leak"

    with pytest.raises(ConfigurationError) as captured:
        parse_secret_json(json.dumps({"SERVICENOW_PASSWORD": sensitive}))

    assert sensitive not in str(captured.value)


def test_secret_json_defaults_to_fixed_caller_mode() -> None:
    configuration = parse_secret_json(
        json.dumps(
            {
                "SERVICENOW_INSTANCE_URL": "https://fictional.service-now.example/",
                "SERVICENOW_USERNAME": "scheduled-demo-user",
                "SERVICENOW_PASSWORD": "fictional-password",
                "SERVICENOW_CALLER_USER_NAME": "demo.caller",
            }
        ),
        environment={},
    )

    assert configuration.credentials.instance_url == "https://fictional.service-now.example"
    assert configuration.credentials.username == "scheduled-demo-user"
    assert configuration.credentials.password == "fictional-password"
    assert configuration.caller == CallerConfiguration("fixed", "demo.caller")


def test_random_caller_mode_does_not_require_fixed_user_name() -> None:
    configuration = parse_secret_json(
        json.dumps(
            {
                "SERVICENOW_INSTANCE_URL": "https://fictional.service-now.example",
                "SERVICENOW_USERNAME": "scheduled-demo-user",
                "SERVICENOW_PASSWORD": "fictional-password",
            }
        ),
        environment={"SERVICENOW_CALLER_MODE": "random"},
    )

    assert configuration.caller == CallerConfiguration("random", None)


def test_fixed_caller_configuration_requires_safe_user_name() -> None:
    with pytest.raises(ConfigurationError, match="CALLER_USER_NAME"):
        caller_configuration_from_values({}, environment={})

    with pytest.raises(ConfigurationError, match="CALLER_MODE"):
        caller_configuration_from_values(
            {},
            environment={"SERVICENOW_CALLER_MODE": "unsupported"},
        )


def test_live_mode_requires_secret_file_but_dry_run_makes_no_request() -> None:
    transport = FakeTransport([])

    result = generate_incident(
        dataset=DEFAULT_DATASET,
        scenario="connect-outbound",
        dry_run=True,
        secret_file=None,
        correlation_factory=lambda: FIXED_CORRELATION_ID,
        transport=transport,
        environment={"SERVICENOW_CALLER_MODE": "random"},
    )

    assert result.mode == "dry-run"
    assert result.caller_mode == "random"
    assert result.caller_resolved is False
    assert result.http_status is None
    assert not transport.calls

    with pytest.raises(ConfigurationError, match="secret file"):
        generate_incident(
            dataset=DEFAULT_DATASET,
            scenario="connect-outbound",
            dry_run=False,
            secret_file=None,
            correlation_factory=lambda: FIXED_CORRELATION_ID,
            transport=transport,
            environment={"SERVICENOW_CALLER_MODE": "random"},
        )


def test_cli_dry_run_executes_from_repository_root() -> None:
    environment = {**os.environ, "SERVICENOW_CALLER_MODE": "random"}
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/generate_scheduled_incident.py",
            "--scenario",
            "connect-outbound",
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["selected_scenario"] == "connect-outbound"
    assert result["mode"] == "dry-run"
    assert result["caller_mode"] == "random"
    assert result["caller_resolved"] is False
    assert result["http_status"] is None
    assert not any("sys_id" in key for key in result)


def test_scenario_selection_is_deterministic_when_requested() -> None:
    scenarios = load_active_scenarios()

    selected, template = select_scenario(
        scenarios,
        "connect-outbound",
        chooser=lambda _: "database-pool",
    )

    assert selected == "connect-outbound"
    assert "cluster:connect-outbound" in template["tags"]
    assert len(scenarios) == 10


def test_default_selection_uses_one_active_template() -> None:
    scenarios = load_active_scenarios()

    selected, template = select_scenario(
        scenarios,
        None,
        chooser=lambda names: names[-1],
    )

    assert selected == sorted(scenarios)[-1]
    assert template["active"] is True


def test_generated_payload_is_active_synthetic_and_unresolved() -> None:
    template = load_active_scenarios()["connect-outbound"]
    payload = build_scheduled_payload(template, correlation_id=FIXED_CORRELATION_ID)

    assert payload["active"] is True
    assert payload["assignment_group"] == ""
    assert payload["cmdb_ci"] == ""
    assert payload["correlation_id"].endswith(str(FIXED_CORRELATION_ID))
    assert json.dumps(payload).count(SCHEDULED_MARKER) == 1
    for field in ("root_cause", "resolution", "close_notes", "resolved_at", "close_code"):
        assert field not in payload


def test_fixed_caller_requires_one_exact_active_user_name() -> None:
    transport = FakeTransport(
        [
            _user_response(
                [
                    {
                        "sys_id": ELIGIBLE_CALLER_ID,
                        "user_name": "demo.caller",
                        "active": "true",
                        "web_service_access_only": "false",
                    }
                ]
            )
        ]
    )
    client = ScheduledIncidentClient(_credentials(), transport=transport)

    caller_id = client.resolve_caller(CallerConfiguration("fixed", "demo.caller"))

    assert caller_id == ELIGIBLE_CALLER_ID
    assert len(transport.calls) == 1
    parsed = urllib.parse.urlparse(str(transport.calls[0]["url"]))
    query = urllib.parse.parse_qs(parsed.query)["sysparm_query"]
    assert query == ["active=true^user_name=demo.caller"]


@pytest.mark.parametrize(
    "records",
    [
        [],
        [
            {"sys_id": ELIGIBLE_CALLER_ID, "user_name": "demo.caller", "active": "true"},
            {"sys_id": SECOND_CALLER_ID, "user_name": "demo.caller", "active": "true"},
        ],
    ],
)
def test_fixed_caller_fails_for_zero_or_multiple_matches(
    records: list[dict[str, object]],
) -> None:
    transport = FakeTransport([_user_response(records)])
    client = ScheduledIncidentClient(_credentials(), transport=transport)

    with pytest.raises(ServiceNowError, match="caller resolution failed"):
        client.resolve_caller(CallerConfiguration("fixed", "demo.caller"))

    assert len(transport.calls) == 1


def test_random_caller_excludes_non_human_users_and_uses_secure_choice_hook() -> None:
    transport = FakeTransport(
        [
            _user_response(
                [
                    {
                        "sys_id": ELIGIBLE_CALLER_ID,
                        "user_name": "fictional.user",
                        "active": "true",
                        "web_service_access_only": "false",
                    },
                    {
                        "sys_id": SECOND_CALLER_ID,
                        "user_name": "second.user",
                        "active": True,
                        "web_service_access_only": False,
                    },
                    {
                        "sys_id": EXCLUDED_CALLER_ID,
                        "user_name": "integration.bot",
                        "active": "true",
                        "web_service_access_only": "false",
                    },
                    {
                        "sys_id": "44444444444444444444444444444444",
                        "user_name": "web.only",
                        "active": "true",
                        "web_service_access_only": "true",
                    },
                    {
                        "sys_id": "55555555555555555555555555555555",
                        "user_name": "",
                        "active": "true",
                        "web_service_access_only": "false",
                    },
                ]
            )
        ]
    )
    choices: list[tuple[str, ...]] = []

    def choose(options: Sequence[str]) -> str:
        choices.append(tuple(options))
        return options[-1]

    client = ScheduledIncidentClient(_credentials(), transport=transport)
    caller_id = client.resolve_caller(
        CallerConfiguration("random", None),
        chooser=choose,
    )

    assert caller_id == SECOND_CALLER_ID
    assert choices == [(ELIGIBLE_CALLER_ID, SECOND_CALLER_ID)]


def test_random_caller_failure_prevents_incident_creation(tmp_path: Path) -> None:
    secret_file = tmp_path / "servicenow.json"
    secret_file.write_text(
        json.dumps(
            {
                "SERVICENOW_INSTANCE_URL": "https://fictional.service-now.example",
                "SERVICENOW_USERNAME": "scheduled-demo-user",
                "SERVICENOW_PASSWORD": "fictional-password",
            }
        ),
        encoding="utf-8",
    )
    transport = FakeTransport(
        [
            _user_response(
                [
                    {
                        "sys_id": EXCLUDED_CALLER_ID,
                        "user_name": "svc.integration",
                        "active": "true",
                        "web_service_access_only": "false",
                    }
                ]
            )
        ]
    )

    with pytest.raises(ServiceNowError, match="caller resolution failed"):
        generate_incident(
            dataset=DEFAULT_DATASET,
            scenario="connect-outbound",
            dry_run=False,
            secret_file=secret_file,
            correlation_factory=lambda: FIXED_CORRELATION_ID,
            transport=transport,
            sleep=lambda _: None,
            environment={"SERVICENOW_CALLER_MODE": "random"},
        )

    assert [call["method"] for call in transport.calls] == ["GET"]


def test_live_generation_sets_caller_without_exposing_identity(tmp_path: Path) -> None:
    secret_file = tmp_path / "servicenow.json"
    secret_file.write_text(
        json.dumps(
            {
                "SERVICENOW_INSTANCE_URL": "https://fictional.service-now.example",
                "SERVICENOW_USERNAME": "scheduled-demo-user",
                "SERVICENOW_PASSWORD": "fictional-password",
            }
        ),
        encoding="utf-8",
    )
    transport = FakeTransport(
        [
            _user_response(
                [
                    {
                        "sys_id": ELIGIBLE_CALLER_ID,
                        "user_name": "fictional.user",
                        "active": "true",
                        "web_service_access_only": "false",
                    }
                ]
            ),
            _created_response(),
        ]
    )

    result = generate_incident(
        dataset=DEFAULT_DATASET,
        scenario="connect-outbound",
        dry_run=False,
        secret_file=secret_file,
        caller_chooser=lambda options: options[0],
        correlation_factory=lambda: FIXED_CORRELATION_ID,
        transport=transport,
        sleep=lambda _: None,
        environment={"SERVICENOW_CALLER_MODE": "random"},
    )

    assert result.caller_mode == "random"
    assert result.caller_resolved is True
    assert result.created_incident_number == "INC9012345"
    post_payload = json.loads(transport.calls[1]["body"])
    assert post_payload["caller_id"] == ELIGIBLE_CALLER_ID
    safe_output = json.dumps(asdict(result))
    assert ELIGIBLE_CALLER_ID not in safe_output
    assert "fictional.user" not in safe_output
    assert "sys_id" not in safe_output


def test_retries_only_429_and_transient_5xx_with_timeout() -> None:
    transport = FakeTransport(
        [
            HttpResponse(429, b"provider detail"),
            HttpResponse(502, b"provider detail"),
            _created_response(),
        ]
    )
    sleeps: list[float] = []
    client = ScheduledIncidentClient(
        _credentials(),
        transport=transport,
        sleep=sleeps.append,
    )

    created = client.create_incident({"active": True})

    assert created.http_status == 201
    assert created.number == "INC9012345"
    assert len(transport.calls) == 3
    assert sleeps == [1.0, 2.0]
    assert all(call["timeout"] == 20.0 for call in transport.calls)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_does_not_retry_nonretryable_client_failures(status: int) -> None:
    transport = FakeTransport([HttpResponse(status, b"fictional-password provider detail")])
    client = ScheduledIncidentClient(_credentials(), transport=transport)

    with pytest.raises(ServiceNowError) as captured:
        client.create_incident({"active": True})

    assert len(transport.calls) == 1
    assert "fictional-password" not in str(captured.value)
    assert "provider detail" not in str(captured.value)
    assert f"HTTP {status}" in str(captured.value)


def test_provider_response_and_credentials_never_leak_from_invalid_success() -> None:
    transport = FakeTransport(
        [HttpResponse(201, b'{"result":{"detail":"fictional-password provider detail"}}')]
    )
    client = ScheduledIncidentClient(_credentials(), transport=transport)

    with pytest.raises(ServiceNowError) as captured:
        client.create_incident({"active": True})

    assert "fictional-password" not in str(captured.value)
    assert "provider detail" not in str(captured.value)
