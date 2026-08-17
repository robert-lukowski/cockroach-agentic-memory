# Live MVP architecture

## Scope

The live MVP implements deterministic RAG for resolved incident memories. It uses managed AWS and
CockroachDB services, but keeps the model outside every authorization and data-access decision. A
Privacy Guard pre-hook removes configured direct identifiers before vector or generative processing,
then an independent Bedrock privacy reviewer validates only the already-sanitized payload when
redaction was required.

## Request flow

```text
IAM-signed client --------> API Gateway REST API <-------- ServiceNow scoped application
  three original routes       IAM default + one exception     x-api-key, throttled/quota
                                      |
                                      v
                               Python 3.13 Lambda
                                      |
                            Privacy Guard pre-hook
                         deterministic direct-ID redaction
                                      |
                         +------------+------------+
                         |                         |
                         | if redacted             | sanitized request
                         v                         v
                Bedrock Privacy Agent       Titan Text Embeddings V2
                sanitized text only           1024 dimensions
                         |                         |
                         +-----------PASS----------+
                                                   |
                                                   v
                                        CockroachDB Managed MCP
                                        fixed scoped vector query
                                                   |
                                                   v
                                        validated resolved evidence
                                                   |
                                      evidence redaction boundary
                                                   |
                                                   v
                                        Bedrock Investigator
                                      grounded recommendation

Lambda also retrieves the Managed MCP API key from AWS Secrets Manager. CockroachDB operational
memory is stored in `incident_memories` with the cosine vector index.
```

The Lambda calls public managed endpoints and does not require a VPC, NAT gateway, or database
connection string. Managed MCP authentication is a dedicated service-account API key. The original
application routes remain AWS IAM authenticated; the ServiceNow route alone uses a separate API
Gateway API key because it is called by the scoped application REST Message.

## Privacy Guard boundary

Privacy protection is deliberately split into two responsibilities rather than asking a language
model to inspect raw personal data.

1. Application code deterministically redacts configured direct identifiers before any embedding or
   investigator-model call. The current implementation covers email addresses plus explicitly
   labeled phone and human-name fields.
2. If redaction occurred, a second Bedrock call acts as the Privacy Guard validation agent. It sees
   only the sanitized text and the names of redaction categories; it never receives removed values.
3. The reviewer returns only `PASS` or `REVIEW_REQUIRED`. A review-required verdict stops the request
   before embedding, retrieval, or Investigator generation.
4. If the optional secondary review is unavailable, deterministic redaction remains enforced and the
   response reports the degraded audit status without reintroducing removed values.
5. Retrieved evidence is deterministically redacted again before it is projected into the API
   response or provided to the Investigator model.
6. Resolved-memory ingestion applies deterministic redaction before embedding and persistence, so
   configured direct identifiers are not intentionally written into new operational-memory rows.

The API exposes only safe privacy metadata: status, redaction count, category names, and whether the
secondary AI review ran. Removed values are neither returned in that metadata nor rendered by the
Streamlit Privacy Guard card.

This is a bounded direct-identifier control, not a claim of universal PII detection. A production
system would extend the detector policy and validation corpus for organization-specific identifiers,
local formats, and regulatory requirements.

## Deterministic workflows

### Create incident

1. The handler parses JSON and strictly validates `IncidentCreateRequest`.
2. The privacy boundary redacts configured direct identifiers from memory-bearing text fields.
3. The service constructs a stable embedding document from the sanitized incident fields.
4. Titan Text Embeddings V2 returns exactly 1,024 finite numeric values; other responses are rejected.
5. The service assigns a UUID and UTC creation timestamp.
6. The repository maps the domain object to the MCP `insert_rows` tool for `incident_memories`.
7. The API returns the incident ID and timestamp without echoing incident contents.

### Investigate

1. The handler validates `InvestigationRequest` and bounds `top_k` to 1 through 10.
2. Privacy Guard deterministically redacts the current symptoms before any model or vector call.
3. When redaction occurred, the secondary Bedrock Privacy Guard agent reviews only sanitized text.
4. Titan embeds the sanitized symptoms.
5. The repository builds a fixed cosine query with an exact required `scope` predicate and optional
   exact `service` and `environment` predicates.
6. CockroachDB orders results by cosine distance using the distributed vector index.
7. The service rejects malformed, non-finite, over-limit, or cross-scope repository evidence.
8. Retrieved evidence is deterministically redacted before model or response projection.
9. Bedrock Investigator receives only sanitized current symptoms and validated sanitized evidence.
10. The model produces concise diagnosis and numbered-action text without evidence tables or
    incident identifier lists.
11. Application code copies supporting IDs and a fixed evidence projection from repository results;
    the model cannot add, remove, or alter supporting records.
12. Safe `privacy_guard` metadata and per-request timing measurements are returned alongside the
    existing recommendation and evidence fields.

There is no model-directed tool loop and no generic data-access method in the application layer.
The Privacy Guard reviewer is a narrow validation agent and cannot query CockroachDB, choose scope,
or modify the Investigator recommendation.

### Analyze from ServiceNow

1. API Gateway requires the dedicated `x-api-key` on `/servicenow/analyze`; the API-wide IAM default
   continues to apply to every original route.
2. The handler rejects bodies over 32 KiB and strictly validates the exact 12-field payload emitted
   by `AgenticMemoryClient`.
3. Application code maps populated incident fields to `InvestigationRequest`, applying the
   deployment-owned `SERVICENOW_MEMORY_SCOPE` and fixed `top_k=5`.
4. Privacy Guard runs inside the shared investigation service before embedding or Investigator
   generation. No PIN, Streamlit session, or additional ServiceNow permission is involved.
5. The existing investigation service performs embedding, scoped retrieval, evidence validation,
   and grounded recommendation generation without duplicated adapter logic.
6. The response preserves `recommendation` and repository-derived `supporting_incident_ids`, then
   adds `supporting_incidents` with only the incident UUID, readable ServiceNow number, service,
   similarity, root cause, and resolution. Safe privacy and timing metadata are additive fields.
7. The active, unresolved ServiceNow record is not sent through `create_incident` and is not stored.

The readable number is taken from `metadata.incident_number`; invalid or absent values fall back to
the incident UUID, and an absent service becomes `unknown`. Clients should render the readable
number and use the UUID only as a technical fallback. Incomplete optional metadata cannot fail the
whole analysis response, and full metadata is never exposed.

## Ports and adapters

`BedrockGateway` exposes only the Investigator capabilities:

- `generate_embedding(text)`
- `generate_recommendation(symptoms, evidence)`

`PrivacyAuditGateway` is deliberately narrower and exposes only:

- `audit_privacy(text, categories)` returning `PASS` or `REVIEW_REQUIRED`

The live `BedrockRuntimeGateway` implements both contracts using the already-approved generation
model. The Privacy Guard audit therefore requires no additional IAM permission or foundation-model
resource beyond the existing Bedrock policy.

`IncidentRepository` exposes only:

- `save(incident)`
- `find_by_id(incident_id)` for application-owned source idempotency
- `find_similar(scope, embedding, limit, service, environment)`

The live adapters are composed only when `APP_MODE=live` and all required settings validate.
Otherwise bootstrap installs unavailable adapters, so data routes fail closed. Unit tests replace
external dependencies with deterministic in-process fakes and perform no network calls.

The MCP transport uses the official Python SDK and permits only `insert_rows` and `select_query`.
Each repository operation initializes, lists tools, and calls its allowlisted tool inside one
uninterrupted Streamable HTTP `ClientSession`; the SDK owns JSON-RPC framing and session-ID
handling. The query tool receives SQL created inside the repository adapter from a fixed query
shape. Requests, prompts, and model output cannot provide SQL or an MCP tool name.

Source-aware ingestion converts a validated `source_id` to a deterministic UUID. The service uses a
fixed primary-key lookup, avoids embedding and writing when stored sanitized fields already match,
and uses an application-owned upsert when reviewed fields change. `verify_only` performs only the
lookup and comparison. Callers never supply the UUID or repository query.

## Data model and vector retrieval

`incident_memories` stores the UUID, required scope prefix, incident fields, JSON tags and metadata,
normalized `VECTOR(1024)`, and creation timestamp. The vector index is declared with:

```sql
VECTOR INDEX incident_memories_scope_embedding_idx (
    scope,
    embedding vector_cosine_ops
)
```

An equality predicate on `scope` is always present so the prefix index can be used and one logical
scope cannot retrieve another scope's memories. The migration enables vector indexing and creates
the table only if absent, making safe repeated execution possible. Schema evolution should use new,
forward-only migration files rather than editing an applied migration.

## Configuration and secret handling

CloudFormation supplies non-secret runtime settings. The Managed MCP secret ARN is a parameter, but
the secret value never enters CloudFormation or Git. Lambda retrieves it lazily from Secrets Manager
and caches it in memory for the warm execution environment. The secret must contain only the
plaintext Managed MCP API-key secret.

Privacy Guard uses the existing configured generation model and execution role. No personal-data
allowlist, removed value, or privacy secret is stored in source configuration.

Health output reports booleans and non-sensitive process metadata. Expected dependency errors are
mapped to stable API errors, and logs contain request IDs, safe error codes, and MCP tool names only.
Unexpected stack traces must still be treated as sensitive operational data and retained briefly.

## AWS resources

The SAM template creates or updates:

- one regional API Gateway REST API and `v1` stage with default `AWS_IAM` authorization;
- one generated API key, usage plan, and key association for the ServiceNow route only;
- one Python 3.13 Lambda function;
- one named Lambda execution role with inline policies for CloudWatch Logs, the two configured
  Bedrock models, and exactly one Secrets Manager secret;
- one CloudWatch log group with 14-day retention;
- SAM-generated Lambda permissions and API deployment resources.

The Privacy Guard reviewer reuses the configured generation model, so the infrastructure resource
set and IAM model allowlist do not expand for this feature.

The MCP credential secret is intentionally created as a bootstrap resource outside this stack so
its value is never passed through CloudFormation. Its ARN is the only secret metadata supplied to
the stack. CockroachDB Cloud resources are also outside CloudFormation.

## Operational limitations

- Direct-identifier redaction currently covers email addresses and explicitly labeled phone/name
  fields; it is not a universal PII/PHI/DLP engine.
- The secondary Privacy Guard agent is defense in depth. Deterministic redaction is the boundary that
  prevents configured raw identifiers from reaching that reviewer or the Investigator.
- Basic is a single-region development cluster, not a production availability design.
- Managed MCP adds an external network dependency to each repository operation.
- The service-account API key is cached until a cold start; rotation requires overlapping validity
  or a function restart strategy.
- API Gateway usage-plan throttles and quotas are best-effort development controls, not hard cost or
  security boundaries. There is no WAF, private connectivity, or ServiceNow OAuth/mTLS identity.
- No circuit breaker, asynchronous ingestion, or dead-letter queue is in the MVP. The Streamlit
  client performs one bounded retry for HTTP 502/503 responses.
- Tenant isolation is a validated scope convention, not a full authorization policy. A production
  design must derive scope from trusted identity rather than accepting it directly from the body.
- Bedrock output is grounded by instruction and supplied evidence but remains probabilistic.
- The vector index is optimized for the required scope prefix; optional filters are post-filtered.
