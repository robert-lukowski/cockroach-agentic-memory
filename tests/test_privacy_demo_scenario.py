"""Validate the synthetic privacy-sensitive ServiceNow demo scenario shape."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_scheduled_incident import generate_incident


def test_privacy_demo_dataset_is_accepted_by_existing_generator(tmp_path: Path) -> None:
    dataset = tmp_path / "privacy-demo.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "source_id": "servicenow:privacy-demo:00000000000000000000000000000099",
                    "incident_sys_id": "00000000000000000000000000000099",
                    "number": "INC9000099",
                    "state": "In Progress",
                    "active": True,
                    "short_description": (
                        "Customer notification requests time out after deployment"
                    ),
                    "description": (
                        "A customer reports repeated notification timeouts.\n"
                        "Name: Alex Morgan\n"
                        "Email: alex.morgan@example.invalid\n"
                        "Phone: +1 202-555-0147"
                    ),
                    "category": "Software",
                    "subcategory": "Application",
                    "priority": "2 - High",
                    "impact": "2 - Medium",
                    "urgency": "2 - Medium",
                    "assignment_group": "Cloud Platform Operations",
                    "cmdb_ci": "notification-orchestrator",
                    "opened_at": "2026-08-17T09:00:00Z",
                    "resolved_at": None,
                    "close_code": None,
                    "close_notes": None,
                    "root_cause": None,
                    "resolution": None,
                    "tags": [
                        "cluster:privacy-guard",
                        "privacy",
                        "pii",
                        "bedrock",
                        "synthetic",
                    ],
                    "synthetic": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = generate_incident(
        dataset=dataset,
        scenario="privacy-guard",
        dry_run=True,
        secret_file=None,
        environment={"SERVICENOW_CALLER_MODE": "random"},
    )

    assert result.selected_scenario == "privacy-guard"
    assert result.mode == "dry-run"
    assert result.caller_mode == "random"
