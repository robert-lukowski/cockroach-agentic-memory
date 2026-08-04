# MVP architecture

## Scope

This phase establishes local application boundaries and infrastructure scaffolding. It does not
connect to AWS, CockroachDB, or the CockroachDB Managed MCP Server. It does not create or read
secrets, and it does not implement an unrestricted SQL capability.

## Request flow

```text
API Gateway REST API (AWS_IAM)
              |
              v
       Python 3.13 Lambda
              |
       validation models
              |
    IncidentMemoryService
       /              \
      v                v
BedrockGateway    IncidentRepository
  interface           interface
      |                |
 unavailable       unavailable
 adapter now       adapter now

Tests replace both unavailable adapters with deterministic in-process fakes.
```

The service owns orchestration. Adapters cannot bypass validation, select a request scope, or add
supporting incident IDs to a response.

## Deterministic RAG workflows

### Create incident

1. The handler decodes JSON and validates `IncidentCreateRequest`.
2. The service builds a stable embedding document from structured incident fields.
3. `BedrockGateway.generate_embedding` returns exactly 1,024 finite numeric values.
4. The service assigns the UUID and UTC creation timestamp.
5. `IncidentRepository.save` stores the domain object.
6. The API returns only the incident ID and timestamp.

### Investigate

1. The handler validates `InvestigationRequest` and bounds `top_k` to 1–10.
2. The symptoms are embedded through `BedrockGateway`.
3. `IncidentRepository.find_similar` searches within the required scope and optional service and
   environment filters.
4. The service rejects cross-scope or malformed repository results.
5. Retrieved evidence is passed to `BedrockGateway.generate_recommendation`.
6. Supporting IDs and similarity values are copied from repository evidence, not model output.

There is no model-directed tool loop in this phase.

## Ports and trust boundaries

`BedrockGateway` exposes only:

- `generate_embedding(text)`
- `generate_recommendation(symptoms, evidence)`

`IncidentRepository` exposes only:

- `save(incident)`
- `find_similar(scope, embedding, limit, service, environment)`

There is deliberately no generic query, SQL, MCP tool, AWS client, or secret accessor in the
application surface. The future Managed MCP adapter must translate these narrow methods into
allowlisted MCP calls and must never accept model-generated SQL.

## Current SAM resources

The template defines the resources that a later approved deployment would create:

- Regional API Gateway REST API with AWS IAM authorization.
- One Python 3.13 Lambda function.
- One least-privilege Lambda execution role with log-write permissions only.
- One CloudWatch log group with 14-day retention.
- SAM-generated permissions connecting API Gateway to Lambda.

There are no Bedrock permissions, secrets, S3 buckets, VPC resources, or database resources in the
current template. The default handler uses unavailable adapters so an accidental deployment cannot
call Bedrock or CockroachDB.

## Future adapter phase

A later proposal may add:

- An Amazon Titan Text Embeddings V2 adapter configured for 1,024 dimensions.
- A separately selected Bedrock generation model adapter.
- A CockroachDB Managed MCP repository adapter.
- A secret ARN parameter and narrowly scoped `secretsmanager:GetSecretValue` permission.
- Narrow Bedrock inference permissions for the selected model resources.
- CockroachDB schema migration and distributed cosine vector index.

Those changes require tests, SAM validation, a full diff and resource review, and explicit approval
under `AGENTS.md` before deployment.
