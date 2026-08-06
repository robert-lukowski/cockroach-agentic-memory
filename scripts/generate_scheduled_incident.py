"""Create one active synthetic ServiceNow incident from a reviewed demo template."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.seed_servicenow_incidents import (
        STATE_MAPPING,
        SYNTHETIC_MARKER,
        ConfigurationError,
        HttpTransport,
        ServiceNowError,
        UrllibTransport,
        load_dataset,
    )
except ModuleNotFoundError:  # Direct execution places the scripts directory on sys.path.
    from seed_servicenow_incidents import (  # type: ignore[no-redef]
        STATE_MAPPING,
        SYNTHETIC_MARKER,
        ConfigurationError,
        HttpTransport,
        ServiceNowError,
        UrllibTransport,
        load_dataset,
    )

SCHEDULED_MARKER = "[AGENTIC_MEMORY_SCHEDULED_DEMO]"
DEFAULT_DATASET = Path("data/servicenow_demo_incidents.json")
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
_SCENARIO_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_INCIDENT_NUMBER_PATTERN = re.compile(r"INC\d{7,}")
_SYS_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_USER_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
_CALLER_MODES = frozenset({"fixed", "random"})
_INTEGRATION_TOKENS = frozenset(
    {"api", "automation", "bot", "integration", "service", "svc", "system", "webservice"}
)
_NON_HUMAN_USER_NAMES = frozenset({"admin", "guest", "maint", "system"})
_RESOLVED_FIELDS = frozenset(
    {"root_cause", "resolution", "close_notes", "resolved_at", "close_code"}
)


@dataclass(frozen=True, slots=True)
class ServiceNowCredentials:
    instance_url: str
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class CallerConfiguration:
    mode: str
    user_name: str | None


@dataclass(frozen=True, slots=True)
class ServiceNowConfiguration:
    credentials: ServiceNowCredentials
    caller: CallerConfiguration


@dataclass(frozen=True, slots=True)
class CreatedIncident:
    http_status: int
    number: str


@dataclass(frozen=True, slots=True)
class GenerationResult:
    selected_scenario: str
    mode: str
    caller_mode: str
    caller_resolved: bool
    http_status: int | None
    created_incident_number: str | None


def caller_configuration_from_values(
    values: Mapping[str, Any],
    environment: Mapping[str, str] | None = None,
) -> CallerConfiguration:
    environment_values = os.environ if environment is None else environment
    raw_mode = environment_values.get(
        "SERVICENOW_CALLER_MODE",
        values.get("SERVICENOW_CALLER_MODE", "fixed"),
    )
    if not isinstance(raw_mode, str) or raw_mode not in _CALLER_MODES:
        raise ConfigurationError("SERVICENOW_CALLER_MODE must be fixed or random.")
    raw_user_name = environment_values.get(
        "SERVICENOW_CALLER_USER_NAME",
        values.get("SERVICENOW_CALLER_USER_NAME"),
    )
    if raw_mode == "fixed":
        if (
            not isinstance(raw_user_name, str)
            or _USER_NAME_PATTERN.fullmatch(raw_user_name) is None
        ):
            raise ConfigurationError(
                "SERVICENOW_CALLER_USER_NAME is required for fixed caller mode."
            )
        return CallerConfiguration(raw_mode, raw_user_name)
    return CallerConfiguration(raw_mode, None)


def parse_secret_json(
    raw_secret: str,
    environment: Mapping[str, str] | None = None,
) -> ServiceNowConfiguration:
    """Parse the expected secret without reflecting any secret content in failures."""
    try:
        payload = json.loads(raw_secret)
    except json.JSONDecodeError as error:
        raise ConfigurationError("The ServiceNow secret is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise ConfigurationError("The ServiceNow secret must be a JSON object.")

    keys = ("SERVICENOW_INSTANCE_URL", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD")
    values: dict[str, str] = {}
    for key in keys:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ConfigurationError("The ServiceNow secret is missing required configuration.")
        values[key] = value

    instance_url = values["SERVICENOW_INSTANCE_URL"].rstrip("/")
    parsed_url = urllib.parse.urlparse(instance_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
        or parsed_url.path not in {"", "/"}
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ConfigurationError(
            "SERVICENOW_INSTANCE_URL must be a credential-free HTTPS origin."
        )
    return ServiceNowConfiguration(
        credentials=ServiceNowCredentials(
            instance_url=instance_url,
            username=values["SERVICENOW_USERNAME"],
            password=values["SERVICENOW_PASSWORD"],
        ),
        caller=caller_configuration_from_values(payload, environment),
    )


def configuration_from_secret_file(
    path: Path | None,
    environment: Mapping[str, str] | None = None,
) -> ServiceNowConfiguration:
    if path is None:
        raise ConfigurationError("A ServiceNow secret file is required for live mode.")
    try:
        raw_secret = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError("The ServiceNow secret file is unavailable.") from error
    return parse_secret_json(raw_secret, environment)


def load_active_scenarios(path: Path = DEFAULT_DATASET) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    for record in load_dataset(path):
        if record.get("active") is not True:
            continue
        tags = record.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ConfigurationError("An active demo template has invalid tags.")
        cluster_tags = [tag.removeprefix("cluster:") for tag in tags if tag.startswith("cluster:")]
        if len(cluster_tags) != 1 or _SCENARIO_PATTERN.fullmatch(cluster_tags[0]) is None:
            raise ConfigurationError("An active demo template has an invalid cluster tag.")
        scenario = cluster_tags[0]
        if scenario in scenarios:
            raise ConfigurationError("The active demo templates contain a duplicate cluster.")
        if record.get("state") not in {"New", "In Progress", "On Hold"}:
            raise ConfigurationError("An active demo template has an invalid state.")
        scenarios[scenario] = record
    if not scenarios:
        raise ConfigurationError("No active demo templates are available.")
    return scenarios


def select_scenario(
    scenarios: Mapping[str, dict[str, Any]],
    requested: str | None,
    *,
    chooser: Callable[[Sequence[str]], str] = secrets.choice,
) -> tuple[str, dict[str, Any]]:
    if requested is not None:
        if _SCENARIO_PATTERN.fullmatch(requested) is None or requested not in scenarios:
            raise ConfigurationError("The requested scenario is unavailable.")
        return requested, scenarios[requested]
    names = sorted(scenarios)
    selected = chooser(names)
    if selected not in scenarios:
        raise ConfigurationError("Scenario selection failed safely.")
    return selected, scenarios[selected]


def build_scheduled_payload(
    template: Mapping[str, Any],
    *,
    correlation_id: uuid.UUID,
) -> dict[str, Any]:
    if template.get("active") is not True:
        raise ConfigurationError("Only active demo templates may be scheduled.")
    description = str(template["description"])
    description = description.replace(SYNTHETIC_MARKER, "").replace(SCHEDULED_MARKER, "").strip()
    payload: dict[str, Any] = {
        "short_description": template["short_description"],
        "description": (
            f"{description}\n\n{SCHEDULED_MARKER}\n"
            f"Correlation ID: {correlation_id}"
        ),
        "category": template["category"],
        "subcategory": template["subcategory"],
        "priority": str(template["priority"]).split(" ", maxsplit=1)[0],
        "impact": str(template["impact"]).split(" ", maxsplit=1)[0],
        "urgency": str(template["urgency"]).split(" ", maxsplit=1)[0],
        "state": STATE_MAPPING[str(template["state"])],
        "active": True,
        "assignment_group": "",
        "cmdb_ci": "",
        "correlation_id": f"agentic-memory-scheduled:{correlation_id}",
    }
    if _RESOLVED_FIELDS.intersection(payload):
        raise ConfigurationError("Scheduled payload contains resolved incident fields.")
    if json.dumps(payload, ensure_ascii=False).count(SCHEDULED_MARKER) != 1:
        raise ConfigurationError("Scheduled synthetic marker construction failed.")
    return payload


class ScheduledIncidentClient:
    """Narrow ServiceNow client for caller resolution and one incident create."""

    def __init__(
        self,
        credentials: ServiceNowCredentials,
        *,
        transport: HttpTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        encoded = base64.b64encode(
            f"{credentials.username}:{credentials.password}".encode()
        ).decode()
        self._base_url = credentials.instance_url
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded}",
        }
        self._transport = transport or UrllibTransport()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleep = sleep

    def _request(self, method: str, path: str, body: bytes | None = None):
        for attempt in range(1, self._max_attempts + 1):
            response = self._transport.request(
                method=method,
                url=self._base_url + path,
                headers=self._headers,
                body=body,
                timeout=self._timeout_seconds,
            )
            if 200 <= response.status < 300:
                return response
            retryable = response.status == 429 or 500 <= response.status <= 599
            if retryable and attempt < self._max_attempts:
                self._sleep(float(2 ** (attempt - 1)))
                continue
            category = "rate limited" if response.status == 429 else "request failed"
            raise ServiceNowError(category, status=response.status)
        raise ServiceNowError("request failed")

    @staticmethod
    def _decode_result(response, *, expect_list: bool):
        try:
            decoded = json.loads(response.body)
        except json.JSONDecodeError as error:
            raise ServiceNowError("invalid response") from error
        result = decoded.get("result") if isinstance(decoded, dict) else None
        if expect_list:
            if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
                raise ServiceNowError("invalid response")
        elif not isinstance(result, dict):
            raise ServiceNowError("invalid response")
        return result

    def _list_users(self, *, query: str, limit: int) -> list[dict[str, Any]]:
        parameters = urllib.parse.urlencode(
            {
                "sysparm_query": query,
                "sysparm_fields": "sys_id,user_name,active,web_service_access_only",
                "sysparm_limit": str(limit),
                "sysparm_display_value": "false",
                "sysparm_exclude_reference_link": "true",
            }
        )
        response = self._request("GET", f"/api/now/table/sys_user?{parameters}")
        return self._decode_result(response, expect_list=True)

    def resolve_caller(
        self,
        configuration: CallerConfiguration,
        *,
        chooser: Callable[[Sequence[str]], str] = secrets.choice,
    ) -> str:
        if configuration.mode == "fixed":
            records = self._list_users(
                query=f"active=true^user_name={configuration.user_name}",
                limit=2,
            )
            matches = [
                record
                for record in records
                if record.get("user_name") == configuration.user_name
                and _is_true(record.get("active"))
                and _valid_sys_id(record.get("sys_id"))
            ]
            if len(matches) != 1:
                raise ServiceNowError("caller resolution failed")
            return str(matches[0]["sys_id"])

        records = self._list_users(
            query="active=true^user_nameISNOTEMPTY",
            limit=1000,
        )
        eligible_ids: list[str] = []
        for record in records:
            user_name = record.get("user_name")
            sys_id = record.get("sys_id")
            if (
                not isinstance(user_name, str)
                or not user_name
                or _USER_NAME_PATTERN.fullmatch(user_name) is None
                or not _is_true(record.get("active"))
                or _is_true(record.get("web_service_access_only"))
                or _obvious_integration_user(user_name)
                or not _valid_sys_id(sys_id)
            ):
                continue
            if sys_id not in eligible_ids:
                eligible_ids.append(sys_id)
        if not eligible_ids:
            raise ServiceNowError("caller resolution failed")
        selected = chooser(tuple(eligible_ids))
        if selected not in eligible_ids:
            raise ServiceNowError("caller resolution failed")
        return selected

    def create_incident(self, payload: Mapping[str, Any]) -> CreatedIncident:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        response = self._request("POST", "/api/now/table/incident", body)
        result = self._decode_result(response, expect_list=False)
        number = result.get("number")
        sys_id = result.get("sys_id")
        if (
            not isinstance(number, str)
            or _INCIDENT_NUMBER_PATTERN.fullmatch(number) is None
            or not _valid_sys_id(sys_id)
        ):
            raise ServiceNowError("invalid response")
        return CreatedIncident(response.status, number)


def _is_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() in {"1", "true"})


def _valid_sys_id(value: Any) -> bool:
    return isinstance(value, str) and _SYS_ID_PATTERN.fullmatch(value) is not None


def _obvious_integration_user(user_name: str) -> bool:
    normalized = user_name.casefold()
    if normalized in _NON_HUMAN_USER_NAMES:
        return True
    tokens = set(re.split(r"[._-]+", normalized))
    return bool(tokens.intersection(_INTEGRATION_TOKENS)) or normalized.startswith(
        ("api", "automation", "bot", "integration", "service", "svc", "system", "webservice")
    )


def generate_incident(
    *,
    dataset: Path,
    scenario: str | None,
    dry_run: bool,
    secret_file: Path | None,
    scenario_chooser: Callable[[Sequence[str]], str] = secrets.choice,
    caller_chooser: Callable[[Sequence[str]], str] = secrets.choice,
    correlation_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    transport: HttpTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    environment: Mapping[str, str] | None = None,
) -> GenerationResult:
    scenarios = load_active_scenarios(dataset)
    selected, template = select_scenario(scenarios, scenario, chooser=scenario_chooser)
    payload = build_scheduled_payload(template, correlation_id=correlation_factory())
    if dry_run:
        caller = caller_configuration_from_values({}, environment)
        return GenerationResult(selected, "dry-run", caller.mode, False, None, None)
    configuration = configuration_from_secret_file(secret_file, environment)
    client = ScheduledIncidentClient(
        configuration.credentials,
        transport=transport,
        sleep=sleep,
    )
    caller_id = client.resolve_caller(configuration.caller, chooser=caller_chooser)
    payload["caller_id"] = caller_id
    created = client.create_incident(payload)
    return GenerationResult(
        selected,
        "live",
        configuration.caller.mode,
        True,
        created.http_status,
        created.number,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--scenario")
    parser.add_argument("--secret-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = generate_incident(
            dataset=args.dataset,
            scenario=args.scenario,
            dry_run=args.dry_run,
            secret_file=args.secret_file,
        )
    except (ConfigurationError, ServiceNowError, KeyError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
