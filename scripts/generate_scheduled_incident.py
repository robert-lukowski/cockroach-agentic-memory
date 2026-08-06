"""Create one active synthetic ServiceNow incident from a reviewed demo template."""

from __future__ import annotations

import argparse
import base64
import json
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
_RESOLVED_FIELDS = frozenset(
    {"root_cause", "resolution", "close_notes", "resolved_at", "close_code"}
)


@dataclass(frozen=True, slots=True)
class ServiceNowCredentials:
    instance_url: str
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class CreatedIncident:
    http_status: int
    number: str
    sys_id: str


@dataclass(frozen=True, slots=True)
class GenerationResult:
    selected_scenario: str
    mode: str
    http_status: int | None
    created_incident_number: str | None
    created_sys_id: str | None


def parse_secret_json(raw_secret: str) -> ServiceNowCredentials:
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
    return ServiceNowCredentials(
        instance_url=instance_url,
        username=values["SERVICENOW_USERNAME"],
        password=values["SERVICENOW_PASSWORD"],
    )


def credentials_from_secret_file(path: Path | None) -> ServiceNowCredentials:
    if path is None:
        raise ConfigurationError("A ServiceNow secret file is required for live mode.")
    try:
        raw_secret = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError("The ServiceNow secret file is unavailable.") from error
    return parse_secret_json(raw_secret)


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
    """Narrow create-only ServiceNow client with redacted bounded failures."""

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
        self._url = credentials.instance_url + "/api/now/table/incident"
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded}",
        }
        self._transport = transport or UrllibTransport()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleep = sleep

    def create_incident(self, payload: Mapping[str, Any]) -> CreatedIncident:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        for attempt in range(1, self._max_attempts + 1):
            response = self._transport.request(
                method="POST",
                url=self._url,
                headers=self._headers,
                body=body,
                timeout=self._timeout_seconds,
            )
            if 200 <= response.status < 300:
                try:
                    decoded = json.loads(response.body)
                except json.JSONDecodeError as error:
                    raise ServiceNowError("invalid response") from error
                result = decoded.get("result") if isinstance(decoded, dict) else None
                number = result.get("number") if isinstance(result, dict) else None
                sys_id = result.get("sys_id") if isinstance(result, dict) else None
                if (
                    not isinstance(number, str)
                    or _INCIDENT_NUMBER_PATTERN.fullmatch(number) is None
                    or not isinstance(sys_id, str)
                    or _SYS_ID_PATTERN.fullmatch(sys_id) is None
                ):
                    raise ServiceNowError("invalid response")
                return CreatedIncident(response.status, number, sys_id)
            retryable = response.status == 429 or 500 <= response.status <= 599
            if retryable and attempt < self._max_attempts:
                self._sleep(float(2 ** (attempt - 1)))
                continue
            category = "rate limited" if response.status == 429 else "request failed"
            raise ServiceNowError(category, status=response.status)
        raise ServiceNowError("request failed")


def generate_incident(
    *,
    dataset: Path,
    scenario: str | None,
    dry_run: bool,
    secret_file: Path | None,
    chooser: Callable[[Sequence[str]], str] = secrets.choice,
    correlation_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    transport: HttpTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> GenerationResult:
    scenarios = load_active_scenarios(dataset)
    selected, template = select_scenario(scenarios, scenario, chooser=chooser)
    payload = build_scheduled_payload(template, correlation_id=correlation_factory())
    if dry_run:
        return GenerationResult(selected, "dry-run", None, None, None)
    credentials = credentials_from_secret_file(secret_file)
    created = ScheduledIncidentClient(
        credentials,
        transport=transport,
        sleep=sleep,
    ).create_incident(payload)
    return GenerationResult(
        selected,
        "live",
        created.http_status,
        created.number,
        created.sys_id,
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
