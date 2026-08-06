"""Safely seed fictional incidents through the ServiceNow Table API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

STATE_MAPPING = {
    "New": "1",
    "In Progress": "2",
    "On Hold": "3",
    "Resolved": "6",
    "Closed": "7",
}
SYNTHETIC_MARKER = "[AGENTIC_MEMORY_SYNTHETIC_DEMO]"
RESOLUTION_START = "[AGENTIC_MEMORY_RESOLVED_DETAILS]"
RESOLUTION_END = "[/AGENTIC_MEMORY_RESOLVED_DETAILS]"
DEFAULT_DATASET = Path("data/servicenow_demo_incidents.json")
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
_NUMBER_PATTERN = re.compile(r"INC\d{7}")
_REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()-]{0,255}")
_SYS_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


class ConfigurationError(RuntimeError):
    """Raised when required non-secret configuration is unavailable or unsafe."""


class ServiceNowError(RuntimeError):
    """Safe ServiceNow failure containing status metadata but no provider body."""

    def __init__(self, category: str, *, status: int | None = None) -> None:
        self.category = category
        self.status = status
        suffix = f" (HTTP {status})" if status is not None else ""
        super().__init__(f"ServiceNow {category}{suffix}.")


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        """Send one HTTPS request with an explicit timeout."""


class UrllibTransport:
    """TLS-verifying standard-library transport."""

    def __init__(self) -> None:
        self._tls_context = ssl.create_default_context()

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=self._tls_context,
            ) as response:
                return HttpResponse(status=response.status, body=response.read())
        except urllib.error.HTTPError as error:
            return HttpResponse(status=error.code, body=error.read())
        except (TimeoutError, urllib.error.URLError) as error:
            raise ServiceNowError("transport failure") from error


class ServiceNowClient:
    """Narrow Table API client with redacted failures and bounded retries."""

    def __init__(
        self,
        *,
        instance_url: str,
        username: str,
        password: str,
        transport: HttpTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        parsed = urllib.parse.urlparse(instance_url.rstrip("/"))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("SERVICENOW_INSTANCE_URL must be a credential-free HTTPS URL.")
        if not username or not password:
            raise ConfigurationError("ServiceNow username and password are required.")
        credential = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._base_url = instance_url.rstrip("/")
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {credential}",
        }
        self._transport = transport or UrllibTransport()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleep = sleep

    def list_records(
        self,
        table: str,
        *,
        query: str,
        fields: Sequence[str],
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        parameters = urllib.parse.urlencode(
            {
                "sysparm_query": query,
                "sysparm_fields": ",".join(fields),
                "sysparm_limit": str(limit),
                "sysparm_display_value": "false",
                "sysparm_exclude_reference_link": "true",
            }
        )
        payload = self._request("GET", f"/api/now/table/{table}?{parameters}")
        result = payload.get("result")
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise ServiceNowError("invalid response")
        return result

    def create_incident(self, payload: Mapping[str, Any]) -> None:
        self._request("POST", "/api/now/table/incident", payload)

    def update_incident(self, sys_id: str, payload: Mapping[str, Any]) -> None:
        if _SYS_ID_PATTERN.fullmatch(sys_id) is None:
            raise ServiceNowError("invalid incident identifier")
        self._request("PATCH", f"/api/now/table/incident/{sys_id}", payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            if payload is not None
            else None
        )
        for attempt in range(1, self._max_attempts + 1):
            response = self._transport.request(
                method=method,
                url=self._base_url + path,
                headers=self._headers,
                body=body,
                timeout=self._timeout_seconds,
            )
            if 200 <= response.status < 300:
                try:
                    decoded = json.loads(response.body) if response.body else {"result": {}}
                except json.JSONDecodeError as error:
                    raise ServiceNowError("invalid response") from error
                if not isinstance(decoded, dict):
                    raise ServiceNowError("invalid response")
                return decoded
            retryable = response.status == 429 or 500 <= response.status <= 599
            if retryable and attempt < self._max_attempts:
                self._sleep(float(2 ** (attempt - 1)))
                continue
            category = "rate limited" if response.status == 429 else "request failed"
            raise ServiceNowError(category, status=response.status)
        raise ServiceNowError("request failed")


@dataclass(slots=True)
class SeedSummary:
    selected: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    missing_assignment_group_reference: int = 0
    missing_cmdb_ci_reference: int = 0


def load_dataset(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError("The dataset could not be loaded as UTF-8 JSON.") from error
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ConfigurationError("The dataset must be a JSON array of objects.")
    numbers = [item.get("number") for item in payload]
    if any(
        not isinstance(number, str) or _NUMBER_PATTERN.fullmatch(number) is None
        for number in numbers
    ):
        raise ConfigurationError("The dataset contains an invalid incident number.")
    if len(numbers) != len(set(numbers)):
        raise ConfigurationError("The dataset contains duplicate incident numbers.")
    return payload


def select_records(
    records: Sequence[dict[str, Any]],
    *,
    only_active: bool,
    only_resolved: bool,
    limit: int | None,
) -> tuple[list[dict[str, Any]], int]:
    if only_active and only_resolved:
        raise ConfigurationError("--only-active and --only-resolved are mutually exclusive.")
    selected = [
        record
        for record in records
        if (not only_active or record.get("active") is True)
        and (not only_resolved or record.get("active") is False)
    ]
    if limit is not None:
        if limit < 1:
            raise ConfigurationError("--limit must be at least 1.")
        selected = selected[:limit]
    return selected, len(records) - len(selected)


def validate_state_mapping(client: ServiceNowClient) -> None:
    dictionary = client.list_records(
        "sys_dictionary",
        query="name=task^element=state",
        fields=("name", "element", "internal_type"),
        limit=2,
    )
    if len(dictionary) != 1:
        raise ConfigurationError(
            "The PDI task.state dictionary entry is unavailable or ambiguous."
        )
    choices = client.list_records(
        "sys_choice",
        query="name=incident^element=state^inactive=false",
        fields=("label", "value"),
        limit=100,
    )
    actual: dict[str, str] = {}
    for choice in choices:
        label = choice.get("label")
        value = choice.get("value")
        if isinstance(label, str) and isinstance(value, str):
            if label in actual and actual[label] != value:
                raise ConfigurationError("The PDI incident state choices are ambiguous.")
            actual[label] = value
    mismatches = {
        label: (expected, actual.get(label))
        for label, expected in STATE_MAPPING.items()
        if actual.get(label) != expected
    }
    if mismatches:
        labels = ", ".join(sorted(mismatches))
        raise ConfigurationError(f"PDI incident state mapping mismatch for: {labels}.")


def _reference_id(
    client: ServiceNowClient,
    *,
    table: str,
    display_name: str,
) -> str | None:
    if _REFERENCE_PATTERN.fullmatch(display_name) is None:
        return None
    matches = client.list_records(
        table,
        query=f"name={display_name}",
        fields=("sys_id", "name"),
        limit=2,
    )
    exact = [item for item in matches if item.get("name") == display_name]
    if len(exact) != 1:
        return None
    sys_id = exact[0].get("sys_id")
    return sys_id if isinstance(sys_id, str) and _SYS_ID_PATTERN.fullmatch(sys_id) else None


def _snow_timestamp(value: str) -> str:
    parsed = time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return time.strftime("%Y-%m-%d %H:%M:%S", parsed)


def build_incident_payload(
    record: Mapping[str, Any],
    *,
    assignment_group_id: str | None,
    cmdb_ci_id: str | None,
) -> dict[str, Any]:
    description = str(record["description"]).replace(SYNTHETIC_MARKER, "").strip()
    payload: dict[str, Any] = {
        "number": record["number"],
        "short_description": record["short_description"],
        "description": f"{description}\n\n{SYNTHETIC_MARKER}",
        "category": record["category"],
        "subcategory": record["subcategory"],
        "priority": str(record["priority"]).split(" ", maxsplit=1)[0],
        "impact": str(record["impact"]).split(" ", maxsplit=1)[0],
        "urgency": str(record["urgency"]).split(" ", maxsplit=1)[0],
        "state": STATE_MAPPING[str(record["state"])],
        "active": bool(record["active"]),
        "assignment_group": assignment_group_id or "",
        "cmdb_ci": cmdb_ci_id or "",
        "opened_at": _snow_timestamp(str(record["opened_at"])),
    }
    if record["active"] is False:
        close_notes = str(record["close_notes"]).strip()
        payload.update(
            {
                "resolved_at": _snow_timestamp(str(record["resolved_at"])),
                "close_code": record["close_code"],
                "close_notes": (
                    f"{close_notes}\n\n{RESOLUTION_START}\n"
                    f"Root cause: {record['root_cause']}\n"
                    f"Resolution: {record['resolution']}\n{RESOLUTION_END}"
                ),
            }
        )
    if json.dumps(payload, ensure_ascii=False).count(SYNTHETIC_MARKER) != 1:
        raise ConfigurationError("Synthetic marker construction failed.")
    return payload


def _same_values(existing: Mapping[str, Any], desired: Mapping[str, Any]) -> bool:
    for field, desired_value in desired.items():
        existing_value = existing.get(field)
        if isinstance(desired_value, bool):
            if str(existing_value).lower() != str(desired_value).lower():
                return False
        elif str(existing_value or "") != str(desired_value):
            return False
    return True


def seed_records(
    records: Sequence[dict[str, Any]],
    *,
    client: ServiceNowClient,
    dry_run: bool = False,
    verify_only: bool = False,
    skipped: int = 0,
    warning: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> SeedSummary:
    summary = SeedSummary(selected=len(records), skipped=skipped)
    fields = (
        "sys_id",
        "number",
        "short_description",
        "description",
        "category",
        "subcategory",
        "priority",
        "impact",
        "urgency",
        "state",
        "active",
        "assignment_group",
        "cmdb_ci",
        "opened_at",
        "resolved_at",
        "close_code",
        "close_notes",
    )
    for record in records:
        number = str(record["number"])
        try:
            group_id = _reference_id(
                client,
                table="sys_user_group",
                display_name=str(record["assignment_group"]),
            )
            if group_id is None:
                summary.missing_assignment_group_reference += 1
                warning(f"warning: {number}: assignment_group reference not found; leaving empty")
            ci_id = _reference_id(
                client,
                table="cmdb_ci",
                display_name=str(record["cmdb_ci"]),
            )
            if ci_id is None:
                summary.missing_cmdb_ci_reference += 1
                warning(f"warning: {number}: cmdb_ci reference not found; leaving empty")
            desired = build_incident_payload(
                record,
                assignment_group_id=group_id,
                cmdb_ci_id=ci_id,
            )
            matches = client.list_records(
                "incident",
                query=f"number={number}",
                fields=fields,
                limit=2,
            )
            if len(matches) > 1:
                summary.failed += 1
                warning(f"warning: {number}: duplicate incident number; no write performed")
                continue
            if not matches:
                if verify_only:
                    summary.failed += 1
                    warning(f"warning: {number}: incident is absent during verification")
                elif dry_run:
                    summary.created += 1
                else:
                    client.create_incident(desired)
                    summary.created += 1
                continue
            existing = matches[0]
            if _same_values(existing, desired):
                summary.unchanged += 1
                continue
            if verify_only:
                summary.failed += 1
                warning(f"warning: {number}: incident differs during verification")
            elif dry_run:
                summary.updated += 1
            else:
                sys_id = existing.get("sys_id")
                if not isinstance(sys_id, str) or _SYS_ID_PATTERN.fullmatch(sys_id) is None:
                    raise ServiceNowError("invalid incident identifier")
                client.update_incident(sys_id, desired)
                summary.updated += 1
        except (ConfigurationError, ServiceNowError, KeyError, TypeError, ValueError):
            summary.failed += 1
            warning(f"warning: {number}: safe processing failure")
    return summary


def configuration_from_environment(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str, str]:
    values = os.environ if environment is None else environment
    names = ("SERVICENOW_INSTANCE_URL", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD")
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise ConfigurationError(
            "Missing required ServiceNow configuration: " + ", ".join(missing) + "."
        )
    return tuple(values[name] for name in names)  # type: ignore[return-value]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int)
    filters = parser.add_mutually_exclusive_group()
    filters.add_argument("--only-active", action="store_true")
    filters.add_argument("--only-resolved", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        records = load_dataset(args.dataset)
        selected, skipped = select_records(
            records,
            only_active=args.only_active,
            only_resolved=args.only_resolved,
            limit=args.limit,
        )
        instance_url, username, password = configuration_from_environment()
        client = ServiceNowClient(
            instance_url=instance_url,
            username=username,
            password=password,
        )
        validate_state_mapping(client)
        summary = seed_records(
            selected,
            client=client,
            dry_run=args.dry_run,
            verify_only=args.verify_only,
            skipped=skipped,
        )
    except (ConfigurationError, ServiceNowError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(summary), sort_keys=True))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
