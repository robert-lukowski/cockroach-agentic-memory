# Live MVP architecture

## Scope

The live MVP implements deterministic RAG for resolved incident memories. It uses managed AWS and
CockroachDB services, but keeps the model outside every authorization and data-access decision. A
future agentic tool loop is intentionally deferred.

## Request flow

```text
IAM-signed client --------> API Gateway REST API <-------- ServiceNow scoped application
  three original routes       IAM default + one exception     x-api-key, throttled/quota
                                      |
                                      v
Python 3.13 Lambda -----> AWS Secrets Manager
      |                  (one MCP API-key secret, cached in-process)
      |
      +-----> Amazon Bedrock Runtime
      |         - Titan Text Embeddings V2, 1024 dimensions
      |         - grounded recommendation through Converse
      |
      +-----> CockroachDB Cloud Managed MCP
                 - insert_rows
                 - fixed, scoped select_query
                      |
                      v
                 CockroachDB Basic
                 incident_memories + cosine vector index
```

The Lambda calls public managed endpoints and does not require a VPC, NAT gateway, or database
connection string. Managed MCP authentication is a dedicated service-account API key. The original
application routes remain AWS IAM authenticated; the ServiceNow route alone uses a separate API
Gateway API key because it is called by the scoped application REST Message.

## Deterministic workflows

### Create incident

1. The handler parses JSON and strictly validates `IncidentCreateRequest`.
2. The service constructs a stable embedding document from the incident's structured fields.
3. Titan Text Embeddings V2 returns exactly 1,024 finite numeric values; other responses are rejected.
4. The service assigns a UUID and UTC creation timestamp.
5. The repository maps the domain object to the MCP `insert_rows` tool for `incident_memories`.
6. The API returns the incident ID and timestamp without echoing incident contents.

### Investigate

1. The handler validates `InvestigationRequest` and bounds `top_k` to 1 through 10.
2. Titan embeds the symptoms.
3. The repository builds a fixed cosine query with an exact required `scope` predicate and optional
   exact `service` and `environment` predicates.
4. CockroachDB orders results by cosine distance using the distributed vector index.
5. The service rejects malformed, non-finite, over-limit, or cross-scope repository evidence.
6. Bedrock receives only the current symptoms and the validated evidence.
7. The model produces recommendation text; supporting IDs and similarity values are copied from the
   repository evidence by application code.

There is no model-directed tool loop and no generic data-access method in the application layer.

### Analyze from ServiceNow

1. API Gateway requires the dedicated `x-api-key` on `/servicenow/analyze`; the API-wide IAM default
   continues to apply to every original route.
2. The handler rejects bodies over 32 KiB and strictly validates the exact 12-field payload emitted
   by `AgenticMemoryClient`.
3. Application code maps populated incident fields to `InvestigationRequest`, applying the
   deployment-owned `SERVICENOW_MEMORY_SCOPE` and fixed `top_k=5`.
4. The existing investigation service performs embedding, scoped retrieval, evidence validation,
   and grounded recommendation generation without duplicated adapter logic.
5. The response contains only `recommendation` and repository-derived
   `supporting_incident_ids`, matching the existing ServiceNow response parser.
6. The active, unresolved ServiceNow record is not sent through `create_incident` and is not stored.

## Ports and adapters

`BedrockGateway` exposes only:

- `generate_embedding(text)`
- `generate_recommendation(symptoms, evidence)`

`IncidentRepository` exposes only:

- `save(incident)`
- `find_by_id(incident_id)` for application-owned source idempotency
- `find_similar(scope, embedding, limit, service, environment)`

The live adapters are composed only when `APP_MODE=live` and all required settings validate.
Otherwise bootstrap installs unavailable adapters, so data routes fail closed. Unit tests replace
both ports with deterministic in-process fakes and perform no network calls.

The MCP transport uses the official Python SDK and permits only `insert_rows` and `select_query`.
Each repository operation initializes, lists tools, and calls its allowlisted tool inside one
uninterrupted Streamable HTTP `ClientSession`; the SDK owns JSON-RPC framing and session-ID
handling. The query tool receives SQL created inside the repository adapter from a fixed query
shape. Requests, prompts, and model output cannot provide SQL or an MCP tool name.

Source-aware ingestion converts a validated `source_id` to a deterministic UUID. The service uses a
fixed primary-key lookup, avoids embedding and writing when stored fields already match, and uses an
application-owned upsert when reviewed fields change. `verify_only` performs only the lookup and
comparison. Callers never supply the UUID or repository query.

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

The MCP credential secret is intentionally created as a bootstrap resource outside this stack so
its value is never passed through CloudFormation. Its ARN is the only secret metadata supplied to
the stack. CockroachDB Cloud resources are also outside CloudFormation.

## Operational limitations

- Basic is a single-region development cluster, not a production availability design.
- Managed MCP adds an external network dependency to each repository operation.
- The service-account API key is cached until a cold start; rotation requires overlapping validity
  or a function restart strategy.
- API Gateway usage-plan throttles and quotas are best-effort development controls, not hard cost or
  security boundaries. There is no WAF, private connectivity, or ServiceNow OAuth/mTLS identity.
- No retry, circuit breaker, asynchronous ingestion, or dead-letter queue is in the MVP.
- Tenant isolation is a validated scope convention, not a full authorization policy. A production
  design must derive scope from trusted identity rather than accepting it directly from the body.
- Bedrock output is grounded by instruction and supplied evidence but remains probabilistic.
- The vector index is optimized for the required scope prefix; optional filters are post-filtered.
