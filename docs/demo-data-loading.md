# Demo data loading

This document describes the two intentionally separate loading paths for the fictional ServiceNow
demo dataset. Neither script connects directly to CockroachDB, accepts SQL, logs request bodies, or
prints credentials.

## Safety model

- `scripts/seed_servicenow_incidents.py` uses only the ServiceNow Table API over verified TLS.
- `scripts/sync_resolved_incidents.py` uses only the IAM-protected backend `POST /incidents` route.
- ServiceNow reference records are looked up by exact display name and are never created.
- Only resolved or closed incidents become operational memories.
- HTTP requests always have a timeout. Retries are limited to three attempts and only apply to
  throttling (`429`) or transient server errors (`5xx`).
- Console output contains counters, incident numbers in safe warnings, and error categories—not
  credentials, authorization headers, full payloads, descriptions, or provider response bodies.

## ServiceNow configuration

Provide these values through the process environment:

```powershell
$env:SERVICENOW_INSTANCE_URL = "https://<private-pdi-host>"
$env:SERVICENOW_USERNAME = "<integration-user>"
$env:SERVICENOW_PASSWORD = "<protected-password>"
```

Do not put these settings in Git, `.env` files, command arguments, transcripts, or screenshots.
Remove the variables after use.

Before any incident write, the script reads the PDI `incident.state` dictionary and active choices.
The expected mapping is declared near the top of the script:

| Label | Value |
| --- | ---: |
| New | 1 |
| In Progress | 2 |
| On Hold | 3 |
| Resolved | 6 |
| Closed | 7 |

The run fails before writes if the current PDI mapping is missing, ambiguous, or different.

## ServiceNow seeding workflow

Start with a read-only plan:

```powershell
.venv\Scripts\python scripts\seed_servicenow_incidents.py --dry-run
```

Useful bounded selections are:

```powershell
.venv\Scripts\python scripts\seed_servicenow_incidents.py --dry-run --limit 3
.venv\Scripts\python scripts\seed_servicenow_incidents.py --dry-run --only-active
.venv\Scripts\python scripts\seed_servicenow_incidents.py --dry-run --only-resolved
.venv\Scripts\python scripts\seed_servicenow_incidents.py --verify-only
```

`--dataset PATH` selects another reviewed dataset. `--dry-run` performs state, reference, duplicate,
and difference checks but does not write. Its `created` and `updated` counters are planned actions.
`--verify-only` performs no writes and reports absent or different records as failures.

For every selected record, the script:

1. resolves `assignment_group` against `sys_user_group` by exact `name`;
2. resolves `cmdb_ci` against `cmdb_ci` by exact `name`;
3. leaves a reference empty and emits a safe incident-number warning if no unique exact match exists;
4. queries `incident` by the validated incident number;
5. fails that record without writing if duplicate numbers exist;
6. creates an absent record, updates only differing relevant fields, or counts an exact match as
   unchanged.

Each incident description contains `[AGENTIC_MEMORY_SYNTHETIC_DEMO]` exactly once. Resolved details
are placed inside a clearly delimited close-notes section because standard incident tables do not
consistently expose dedicated root-cause and resolution fields. Active payloads omit resolution
timestamps, close fields, root cause, and resolution.

After reviewing the dry-run counters, the write and verification commands are:

```powershell
.venv\Scripts\python scripts\seed_servicenow_incidents.py
.venv\Scripts\python scripts\seed_servicenow_incidents.py --verify-only
```

## Resolved-memory synchronization

The synchronizer uses AWS profile `cockroach-hackathon-dev`, region `eu-central-1`, and this default
API base URL:

```text
https://dwb5sj508e.execute-api.eu-central-1.amazonaws.com/v1
```

`AGENTIC_MEMORY_API_BASE_URL` may override the base URL. The request is signed in memory for the
`execute-api` service; AWS credential values and authorization headers are never printed.

Run a local mapping-only plan first:

```powershell
.venv\Scripts\python scripts\sync_resolved_incidents.py --dry-run
```

Then synchronize and independently verify the resulting memories:

```powershell
.venv\Scripts\python scripts\sync_resolved_incidents.py
.venv\Scripts\python scripts\sync_resolved_incidents.py --verify-only
```

The script always skips active records, even when `--limit` is used. It maps the 20 resolved records
to the existing incident contract with scope `servicenow-dev`, a service derived from `cmdb_ci`, a
development environment unless reviewed data indicates another environment, and an allowlisted
metadata object.

## Source-level idempotency

The ingestion contract remains backward compatible: callers that omit `source_id` retain the
original create behavior and receive `201`. Dataset synchronization supplies the stable top-level
`source_id` and the same value in metadata.

For source-aware requests, application code derives a deterministic UUID, performs a fixed
repository lookup by that UUID, and returns one of:

- `201` with `status=created` for a new memory;
- `200` with `status=already_present` when all relevant values match;
- `200` with `status=updated` when the same source has reviewed changes.

The repository uses an application-owned `INSERT ... ON CONFLICT` statement so concurrent calls for
the same source still cannot create duplicate rows. A request with `verify_only=true` and a
`source_id` performs the lookup and returns `already_present`, `absent`, or `different` without
embedding or writing.

This is not a generic query interface: clients cannot provide an incident UUID, SQL, MCP tool name,
or database operation.

## Acceptance check

After both verification runs pass, invoke the existing ServiceNow UI Action on the active Amazon
Connect incident `INC9000003`. Record only safe assertions: HTTP success, a non-empty recommendation,
supporting incident IDs, and whether at least one supporting ID belongs to a newly synchronized demo
memory. Do not record the recommendation content or incident descriptions in terminal output.
