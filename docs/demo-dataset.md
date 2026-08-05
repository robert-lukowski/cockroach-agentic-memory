# Synthetic ServiceNow demo dataset

## Purpose

`data/servicenow_demo_incidents.json` is a deterministic, fictional dataset for demonstrating
Agentic Incident Memory without using operational or personal data. It contains 30 ServiceNow-style
incidents with stable synthetic identifiers and sequential demo numbers from `INC9000001` through
`INC9000030`.

The dataset is intentionally data-only. This change does not include a ServiceNow seed utility, a
CockroachDB synchronization utility, database writes, infrastructure changes, or deployment steps.

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

Every cluster contains two differently worded resolved histories and one active incident. Tags carry
one stable `cluster:` label plus product, symptom, and cause vocabulary useful to embeddings. The
outbound-call scenario also has related histories in the Lambda, IAM, and database clusters. These
cover reserved concurrency exhaustion, an outbound API client timeout, a missing Connect permission
after a role change, an incorrect deployment timeout, and Lambda VPC connection-pool saturation.

## Resolved and active records

Twenty records are resolved or closed. Each includes a concrete observed root cause, applied
resolution, closure code, closure note, and UTC resolution timestamp. These records represent
candidate operational memory because their diagnosis and remediation are known.

Ten records are active with a state of `New`, `In Progress`, or `On Hold`. Their resolution fields
are explicitly `null`. An unresolved symptom must not be stored as historical memory: doing so would
make an unverified theory look like trusted evidence and could ground later recommendations in a
cause or remediation that was never established.

## Future ServiceNow seeding

A later, separately reviewed seed workflow will load all 30 records into the private development
instance. It should use `source_id` as the idempotent external key and either preserve the stable
`incident_sys_id` or maintain an explicit mapping to the instance-assigned sys ID. The importer
should map state, activity, timestamps, classification, assignment, configuration item, closure
fields, and tags without placing credentials or instance details in this repository.

No seed script is included yet. Before one is added, its behavior should be tested against a private
development instance and designed so repeated execution updates the same synthetic records rather
than creating duplicates.

## Future CockroachDB synchronization

A later synchronizer will select only resolved or closed records and map them through the existing
validated backend incident-creation contract. A likely mapping is:

- deployment-owned scope for the ServiceNow demo;
- `cmdb_ci` as the service or component;
- `short_description` as the memory title;
- `description` as symptoms;
- the verified `root_cause` and `resolution` fields as historical evidence;
- tags and non-sensitive ServiceNow metadata for traceability.

Synchronization should call the authenticated backend repository workflow rather than write SQL or
connect directly to CockroachDB. It will need an explicit idempotency design based on `source_id`
before implementation. Active records remain in ServiceNow for live analysis and are excluded from
the operational-memory synchronization path.
