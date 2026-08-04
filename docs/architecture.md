# Live MVP architecture

## Scope

The live MVP implements deterministic RAG for resolved incident memories. It uses managed AWS and
CockroachDB services, but keeps the model outside every authorization and data-access decision. A
future agentic tool loop is intentionally deferred.

## Request flow

```text
IAM-signed client
      |
      v
API Gateway REST API (AWS_IAM)
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
connection string. Managed MCP authentication is a dedicated service-account API key, while client
access to the application remains AWS IAM authenticated.

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

## Ports and adapters

`BedrockGateway` exposes only:

- `generate_embedding(text)`
- `generate_recommendation(symptoms, evidence)`

`IncidentRepository` exposes only:

- `save(incident)`
- `find_similar(scope, embedding, limit, service, environment)`

The live adapters are composed only when `APP_MODE=live` and all required settings validate.
Otherwise bootstrap installs unavailable adapters, so data routes fail closed. Unit tests replace
both ports with deterministic in-process fakes and perform no network calls.

The MCP transport permits only `insert_rows` and `select_query`. The latter receives SQL created
inside the repository adapter from a fixed query shape. Requests, prompts, and model output cannot
provide SQL or an MCP tool name.

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
- No retry, circuit breaker, asynchronous ingestion, rate limiting, WAF, or dead-letter queue is in
  the MVP.
- Tenant isolation is a validated scope convention, not a full authorization policy. A production
  design must derive scope from trusted identity rather than accepting it directly from the body.
- Bedrock output is grounded by instruction and supplied evidence but remains probabilistic.
- The vector index is optimized for the required scope prefix; optional filters are post-filtered.
