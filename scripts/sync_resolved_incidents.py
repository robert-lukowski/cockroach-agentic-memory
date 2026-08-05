"""Synchronize resolved demo incidents through the signed backend ingestion API."""

from __future__ import annotations

import argparse
import json
import os
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

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

DEFAULT_DATASET = Path("data/servicenow_demo_incidents.json")
DEFAULT_API_BASE_URL = "https://dwb5sj508e.execute-api.eu-central-1.amazonaws.com/v1"
AWS_PROFILE = "cockroach-hackathon-dev"
AWS_REGION = "eu-central-1"
MEMORY_SCOPE = "servicenow-dev"
DEFAULT_TIMEOUT_SECONDS = 45.0
MAX_ATTEMPTS = 3
ALLOWED_METADATA_FIELDS = {
    "source_id",
    "incident_sys_id",
    "incident_number",
    "opened_at",
    "resolved_at",
    "category",
    "subcategory",
    "priority",
    "synthetic",
}


class SyncConfigurationError(RuntimeError):
    """Raised for invalid local synchronization configuration."""


class BackendError(RuntimeError):
    """Safe backend failure that never contains a response body or credentials."""

    def __init__(self, category: str, *, status: int | None = None) -> None:
        self.category = category
        self.status = status
        suffix = f" (HTTP {status})" if status is not None else ""
        super().__init__(f"Backend {category}{suffix}.")


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
        body: bytes,
        timeout: float,
    ) -> HttpResponse:
        """Send one HTTPS request with an explicit timeout."""


class UrllibTransport:
    def __init__(self) -> None:
        self._tls_context = ssl.create_default_context()

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
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
            raise BackendError("transport failure") from error


class SignedIncidentClient:
    """SigV4 client limited to POST /incidents."""

    def __init__(
        self,
        *,
        api_base_url: str,
        session: Any,
        transport: HttpTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        base = api_base_url.rstrip("/")
        parsed = urllib.parse.urlparse(base)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise SyncConfigurationError(
                "AGENTIC_MEMORY_API_BASE_URL must be a credential-free HTTPS URL."
            )
        credentials = session.get_credentials()
        if credentials is None:
            raise SyncConfigurationError("AWS profile credentials are unavailable.")
        self._credentials = credentials
        self._url = base + "/incidents"
        self._transport = transport or UrllibTransport()
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleep = sleep

    def submit(self, payload: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        for attempt in range(1, self._max_attempts + 1):
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            request = AWSRequest(method="POST", url=self._url, data=body, headers=headers)
            frozen = self._credentials.get_frozen_credentials()
            SigV4Auth(frozen, "execute-api", AWS_REGION).add_auth(request)
            response = self._transport.request(
                method="POST",
                url=self._url,
                headers=dict(request.headers.items()),
                body=body,
                timeout=self._timeout_seconds,
            )
            if response.status in {200, 201}:
                try:
                    decoded = json.loads(response.body)
                except json.JSONDecodeError as error:
                    raise BackendError("invalid response") from error
                if not isinstance(decoded, dict):
                    raise BackendError("invalid response")
                return response.status, decoded
            retryable = response.status == 429 or 500 <= response.status <= 599
            if retryable and attempt < self._max_attempts:
                self._sleep(float(2 ** (attempt - 1)))
                continue
            category = "rate limited" if response.status == 429 else "request failed"
            raise BackendError(category, status=response.status)
        raise BackendError("request failed")


@dataclass(slots=True)
class SyncSummary:
    selected_resolved: int = 0
    created: int = 0
    already_present: int = 0
    updated: int = 0
    skipped_active: int = 0
    failed: int = 0


def load_dataset(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SyncConfigurationError("The dataset could not be loaded as UTF-8 JSON.") from error
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise SyncConfigurationError("The dataset must be a JSON array of objects.")
    return payload


def _environment(record: Mapping[str, Any]) -> str:
    text = " ".join([*(str(tag) for tag in record["tags"]), str(record["description"])]).lower()
    if "production" in text or "prod" in record["tags"]:
        return "production"
    if "staging" in text or "stage" in record["tags"]:
        return "staging"
    return "development"


def build_memory_payload(record: Mapping[str, Any], *, verify_only: bool = False) -> dict[str, Any]:
    if record.get("active") is not False or record.get("state") not in {"Resolved", "Closed"}:
        raise SyncConfigurationError("Only resolved or closed incidents can become memories.")
    source_id = str(record["source_id"])
    expected_source_id = f"servicenow:demo:{record['incident_sys_id']}"
    if source_id != expected_source_id:
        raise SyncConfigurationError("The incident source_id is not deterministic.")
    tags = list(dict.fromkeys([*record["tags"], "servicenow", "synthetic-demo", "resolved-memory"]))
    metadata = {
        "source_id": source_id,
        "incident_sys_id": record["incident_sys_id"],
        "incident_number": record["number"],
        "opened_at": record["opened_at"],
        "resolved_at": record["resolved_at"],
        "category": record["category"],
        "subcategory": record["subcategory"],
        "priority": record["priority"],
        "synthetic": record["synthetic"],
    }
    if set(metadata) != ALLOWED_METADATA_FIELDS:
        raise SyncConfigurationError("Memory metadata contains unsupported fields.")
    payload: dict[str, Any] = {
        "source_id": source_id,
        "scope": MEMORY_SCOPE,
        "service": record["cmdb_ci"] or record["assignment_group"] or "servicenow-demo",
        "environment": _environment(record),
        "title": record["short_description"],
        "symptoms": record["description"],
        "root_cause": record["root_cause"],
        "resolution": record["resolution"],
        "tags": tags,
        "metadata": metadata,
    }
    if verify_only:
        payload["verify_only"] = True
    return payload


def synchronize_records(
    records: Sequence[dict[str, Any]],
    *,
    client: SignedIncidentClient | None,
    dry_run: bool = False,
    verify_only: bool = False,
    limit: int | None = None,
    warning: Callable[[str], None] = lambda message: print(message, file=sys.stderr),
) -> SyncSummary:
    active_count = sum(record.get("active") is True for record in records)
    resolved = [
        record
        for record in records
        if record.get("active") is False and record.get("state") in {"Resolved", "Closed"}
    ]
    if limit is not None:
        if limit < 1:
            raise SyncConfigurationError("--limit must be at least 1.")
        resolved = resolved[:limit]
    summary = SyncSummary(selected_resolved=len(resolved), skipped_active=active_count)
    for record in resolved:
        number = str(record.get("number", "unknown"))
        try:
            payload = build_memory_payload(record, verify_only=verify_only)
            if dry_run:
                continue
            if client is None:
                raise SyncConfigurationError("A signed backend client is required.")
            _, response = client.submit(payload)
            status = response.get("status")
            if status == "created":
                summary.created += 1
            elif status == "already_present":
                summary.already_present += 1
            elif status == "updated":
                summary.updated += 1
            elif verify_only and status in {"absent", "different"}:
                summary.failed += 1
                warning(f"warning: {number}: memory verification status is {status}")
            else:
                raise BackendError("invalid response")
        except (BackendError, SyncConfigurationError, KeyError, TypeError, ValueError):
            summary.failed += 1
            warning(f"warning: {number}: safe synchronization failure")
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        records = load_dataset(args.dataset)
        client = None
        if not args.dry_run:
            api_base_url = os.environ.get("AGENTIC_MEMORY_API_BASE_URL", DEFAULT_API_BASE_URL)
            session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
            client = SignedIncidentClient(api_base_url=api_base_url, session=session)
        summary = synchronize_records(
            records,
            client=client,
            dry_run=args.dry_run,
            verify_only=args.verify_only,
            limit=args.limit,
        )
    except (BackendError, SyncConfigurationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(summary), sort_keys=True))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
