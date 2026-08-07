# Synthetic ServiceNow demo dataset

## Purpose

`data/servicenow_demo_incidents.json` is a deterministic, fictional dataset for demonstrating
Agentic Incident Memory without using operational or personal data. It contains 60 ServiceNow-style
incidents with stable synthetic identifiers and sequential demo numbers from `INC9000001` through
`INC9000060`.

The reviewed loading utilities keep ServiceNow seeding and operational-memory synchronization as
separate, explicit workflows. Neither path connects directly to CockroachDB or accepts SQL.

## Cluster design

The records form ten semantic retrieval clusters:

1. Amazon Connect outbound call failures
2. Amazon Connect call drops after transfer
3. Lambda timeout and concurrency exhaustion
4. Bedrock throttling and transient generation failures
5. GitHub Actions deployment failures
6. IAM and Secrets Manager permission failures
7. Voicebot session context loss
8. Multilingual routing and queue misconfiguration
9. ServiceNow REST integration failures
10. Database connection pool saturation

Every cluster contains five resolved histories with distinct failure mechanisms and one active
incident. Tags carry one stable `cluster:` label plus product, symptom, and cause vocabulary useful
to embeddings. The outbound-call scenario also has related histories in the Lambda, IAM, and
database clusters. Together they cover capacity exhaustion, timeout configuration, destination
validation, permission regressions, contact-flow configuration, and connection-pool saturation.

## Resolved and active records

Fifty records are resolved or closed. Each includes a concrete observed root cause, applied
resolution, closure code, closure note, and UTC resolution timestamp. These records represent
operational memory because their diagnosis and remediation are known and have been synchronized
through the authenticated application ingestion path.

Ten records are active with a state of `New`, `In Progress`, or `On Hold`. Their resolution fields
are explicitly `null`. An unresolved symptom must not be stored as historical memory: doing so would
make an unverified theory look like trusted evidence and could ground later recommendations in a
cause or remediation that was never established.

## ServiceNow seeding

`scripts/seed_servicenow_incidents.py` loads all 60 records into the private development instance.
It identifies records by the stable incident number, validates the PDI state choices before writes,
and supports dry-run and verify-only modes. Unsupported demo category labels use the PDI's active
generic `Inquiry / Help` value, unsupported subcategories remain empty, and ServiceNow derives
priority from impact and urgency. Missing assignment-group or configuration-item references also
remain empty; the loader never creates reference records.

The verified expansion run preserved the original 30 records as unchanged and created the 30 new
resolved records. A subsequent verify-only run reported all 60 records unchanged.

## CockroachDB synchronization

`scripts/sync_resolved_incidents.py` selects only resolved or closed records and maps them through
the existing validated backend incident-creation contract:

- deployment-owned scope for the ServiceNow demo;
- `cmdb_ci` as the service or component;
- `short_description` as the memory title;
- `description` as symptoms;
- the verified `root_cause` and `resolution` fields as historical evidence;
- tags and non-sensitive ServiceNow metadata for traceability.

Synchronization calls the IAM-authenticated `POST /incidents` workflow rather than writing SQL or
connecting directly to CockroachDB. Stable `source_id` values provide application-level
idempotency. The verified corpus contains 50 resolved operational memories; all ten active records
remain in ServiceNow for live analysis and are excluded from synchronization.
