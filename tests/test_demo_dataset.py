"""Validation for the fictional ServiceNow hackathon demo dataset."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

DATASET_PATH = Path("data/servicenow_demo_incidents.json")
EXPECTED_FIELDS = {
    "source_id",
    "incident_sys_id",
    "number",
    "state",
    "active",
    "short_description",
    "description",
    "category",
    "subcategory",
    "priority",
    "impact",
    "urgency",
    "assignment_group",
    "cmdb_ci",
    "opened_at",
    "resolved_at",
    "close_code",
    "close_notes",
    "root_cause",
    "resolution",
    "tags",
    "synthetic",
}
ALWAYS_STRING_FIELDS = EXPECTED_FIELDS - {
    "active",
    "resolved_at",
    "close_code",
    "close_notes",
    "root_cause",
    "resolution",
    "tags",
    "synthetic",
}
RESOLUTION_FIELDS = {
    "resolved_at",
    "close_code",
    "close_notes",
    "root_cause",
    "resolution",
}
RESOLVED_STATES = {"Resolved", "Closed"}
ACTIVE_STATES = {"New", "In Progress", "On Hold"}
EXPECTED_CLUSTERS = {
    "cluster:connect-outbound",
    "cluster:connect-transfer",
    "cluster:lambda-capacity",
    "cluster:bedrock-transient",
    "cluster:github-actions",
    "cluster:iam-secrets",
    "cluster:voicebot-context",
    "cluster:multilingual-routing",
    "cluster:servicenow-rest",
    "cluster:database-pool",
}
TEXT_FIELDS = {
    "short_description",
    "description",
    "category",
    "subcategory",
    "priority",
    "impact",
    "urgency",
    "assignment_group",
    "cmdb_ci",
    "close_code",
    "close_notes",
    "root_cause",
    "resolution",
}
SECRET_LIKE_PATTERNS = {
    "email address": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "assigned credential": re.compile(
        r"\b(?:password|passwd|token|secret|api[_ -]?key)\s*[:=]\s*[^\s,;]+",
        re.I,
    ),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "JSON web token": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\."),
    "account identifier": re.compile(r"\b\d{12}\b"),
    "phone number": re.compile(r"(?<!\w)(?:\+?\d[ .()-]*){10,}(?!\w)"),
}
EXISTING_RECORDS_DIGEST = "ee9c294af2df5ab86cf6b08a551f406ecd0e54f1a060481d94be9fe4fa70fa92"


@pytest.fixture(scope="module")
def incidents() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as dataset_file:
        payload = json.load(dataset_file)
    assert isinstance(payload, list)
    return payload


def _utc_timestamp(value: str) -> datetime:
    assert value.endswith("Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo == UTC
    return parsed


def _cluster_tag(incident: dict[str, Any]) -> str:
    cluster_tags = [tag for tag in incident["tags"] if tag.startswith("cluster:")]
    assert len(cluster_tags) == 1
    return cluster_tags[0]


def _searchable_text(incident: dict[str, Any]) -> str:
    values = [incident[field] for field in TEXT_FIELDS if incident[field] is not None]
    values.extend(incident["tags"])
    return "\n".join(values)


def test_dataset_has_exact_size_schema_and_types(incidents) -> None:
    assert len(incidents) == 60
    for incident in incidents:
        assert isinstance(incident, dict)
        assert set(incident) == EXPECTED_FIELDS
        for field in ALWAYS_STRING_FIELDS:
            assert isinstance(incident[field], str)
            assert incident[field].strip()
        assert isinstance(incident["active"], bool)
        assert incident["synthetic"] is True
        assert isinstance(incident["tags"], list)
        assert incident["tags"]
        assert len(incident["tags"]) == len(set(incident["tags"]))
        assert all(isinstance(tag, str) and tag.strip() for tag in incident["tags"])


def test_dataset_uses_stable_unique_identifiers(incidents) -> None:
    numbers = [incident["number"] for incident in incidents]
    sys_ids = [incident["incident_sys_id"] for incident in incidents]
    source_ids = [incident["source_id"] for incident in incidents]

    assert numbers == [f"INC{9_000_000 + index}" for index in range(1, 61)]
    assert sys_ids == [f"{index:032x}" for index in range(1, 61)]
    assert len(numbers) == len(set(numbers))
    assert len(sys_ids) == len(set(sys_ids))
    assert len(source_ids) == len(set(source_ids))
    for incident in incidents:
        assert re.fullmatch(r"[0-9a-f]{32}", incident["incident_sys_id"])
        assert incident["source_id"] == f"servicenow:demo:{incident['incident_sys_id']}"


def test_resolved_and_active_consistency(incidents) -> None:
    resolved = [incident for incident in incidents if not incident["active"]]
    active = [incident for incident in incidents if incident["active"]]

    assert len(resolved) == 50
    assert len(active) == 10
    for incident in resolved:
        assert incident["state"] in RESOLVED_STATES
        assert all(
            isinstance(incident[field], str) and incident[field].strip()
            for field in RESOLUTION_FIELDS
        )
        assert _utc_timestamp(incident["resolved_at"]) >= _utc_timestamp(
            incident["opened_at"]
        )
    for incident in active:
        assert incident["state"] in ACTIVE_STATES
        assert all(incident[field] is None for field in RESOLUTION_FIELDS)
        _utc_timestamp(incident["opened_at"])


def test_every_cluster_has_five_histories_and_one_active_case(incidents) -> None:
    cluster_counts = Counter(_cluster_tag(incident) for incident in incidents)

    assert set(cluster_counts) == EXPECTED_CLUSTERS
    assert set(cluster_counts.values()) == {6}
    for cluster in EXPECTED_CLUSTERS:
        members = [incident for incident in incidents if _cluster_tag(incident) == cluster]
        assert sum(not incident["active"] for incident in members) == 5
        assert sum(incident["active"] for incident in members) == 1
        assert len({incident["short_description"] for incident in members}) == 6
        assert all(
            len(incident["root_cause"]) >= 40 and len(incident["resolution"]) >= 40
            for incident in members
            if not incident["active"]
        )


def test_original_thirty_records_remain_stable(incidents) -> None:
    canonical = json.dumps(
        incidents[:30],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert hashlib.sha256(canonical).hexdigest() == EXISTING_RECORDS_DIGEST


def test_new_records_add_three_distinct_resolved_histories_per_cluster(incidents) -> None:
    new_records = incidents[30:]
    new_cluster_counts = Counter(_cluster_tag(incident) for incident in new_records)

    assert len(new_records) == 30
    assert set(new_cluster_counts) == EXPECTED_CLUSTERS
    assert set(new_cluster_counts.values()) == {3}
    assert all(not incident["active"] for incident in new_records)
    assert all(incident["state"] in RESOLVED_STATES for incident in new_records)
    assert len({incident["root_cause"] for incident in new_records}) == 30
    assert len({incident["resolution"] for incident in new_records}) == 30


def test_outbound_demo_ticket_has_multiple_plausible_historical_matches(incidents) -> None:
    target = next(incident for incident in incidents if incident["number"] == "INC9000003")
    resolved_texts = [
        _searchable_text(incident).lower() for incident in incidents if not incident["active"]
    ]
    required_causes = (
        ("reserved concurrency", "outbound"),
        ("outbound contact api", "timeout"),
        ("vpc database pool", "lambda"),
        ("connect", "role-policy"),
        ("deployment", "timeout"),
    )

    assert target["short_description"] == (
        "Amazon Connect outbound calls fail after Lambda deployment"
    )
    for terms in required_causes:
        assert any(all(term in text for term in terms) for text in resolved_texts)
    assert all(
        target["short_description"] != incident["short_description"]
        for incident in incidents
        if not incident["active"]
    )


def test_dataset_contains_no_obvious_credentials_or_personal_contact_data(incidents) -> None:
    for incident in incidents:
        searchable_text = _searchable_text(incident)
        for label, pattern in SECRET_LIKE_PATTERNS.items():
            assert pattern.search(searchable_text) is None, (
                f"{incident['number']} contains an apparent {label}"
            )
