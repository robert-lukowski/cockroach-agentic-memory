# Agentic Incident Memory

Agentic Incident Memory is a deterministic retrieval-augmented incident-response API for the
CockroachDB x AWS Hackathon. Resolved incidents become scoped, vector-searchable memories;
investigations retrieve related evidence before Amazon Bedrock produces a grounded recommendation.

The MVP deliberately does not use a model-directed tool loop. The model cannot select tools, issue
SQL, choose a tenant scope, or decide which incident IDs appear in the response.

## Live MVP

- Python 3.13 on AWS Lambda behind an IAM-authorized regional API Gateway REST API.
- Amazon Titan Text Embeddings V2 with normalized 1,024-dimensional vectors.
- Amazon Bedrock Converse with an in-region generation model.
- CockroachDB Basic and its distributed cosine vector index.
- CockroachDB Cloud Managed MCP over Streamable HTTP.
- A dedicated MCP service-account API key retrieved from AWS Secrets Manager at runtime.
- Narrow application ports, strict validation, fail-closed configuration, and redacted logging.

The infrastructure definition is in [`template.yaml`](template.yaml), the migration is in
[`db/migrations/001_incident_memories.sql`](db/migrations/001_incident_memories.sql), and the trust
boundaries are documented in [`docs/architecture.md`](docs/architecture.md).

## API

All deployed routes require AWS Signature Version 4 authorization for the `execute-api` service.

### `POST /incidents`

Validates a resolved incident, embeds a stable representation of its fields, and stores it through
the constrained repository interface. A successful response has status `201` and contains only the
generated `incident_id` and `created_at` timestamp. See
[`events/create-incident.json`](events/create-incident.json).

Required fields are `scope`, `service`, `environment`, `title`, `symptoms`, `root_cause`, and
`resolution`. Optional fields are `tags` and `metadata`; unknown fields are rejected.

### `POST /investigations`

Embeds the submitted symptoms, retrieves up to `top_k` incidents in the exact requested scope, and
passes the evidence to Bedrock. The application copies `supporting_incident_ids` from retrieved rows,
not from model output. See [`events/investigate.json`](events/investigate.json).

### `GET /health`

Returns process and configuration status only. It does not return model IDs, cluster IDs, secret
ARNs, API keys, environment contents, or credential state.

## Local development

Prerequisites are Python 3.13 and AWS SAM CLI. Tests inject local fakes and make no network calls.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pip install -r src\requirements.txt
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pytest
sam validate --lint --region eu-central-1
sam build
git diff --check
```

`sam build` writes generated artifacts under the ignored `.aws-sam/` directory.
On Windows, SAM's dependency resolver evaluates the official MCP SDK's Windows-only `pywin32`
marker while selecting Lambda wheels. The runtime dependency closure is therefore fully pinned;
run the build in PowerShell with `$env:PIP_NO_DEPS="1"` so SAM uses that lock without recursively
selecting the Windows-only package. Docker/Linux builds do not require this workaround.

## Development deployment

The development deployment uses AWS profile `cockroach-hackathon-dev`, region `eu-central-1`, and
stack name `cockroach-agentic-memory-dev`. The named profile must resolve to a non-root principal.

Before deploying:

1. Create the CockroachDB Basic cluster and dedicated, cluster-scoped MCP service account.
2. Store the API-key secret as the plaintext value of a dedicated Secrets Manager secret. Never put
   the value in a shell transcript, parameter file, CloudFormation, or Git.
3. Run the idempotent migration against `defaultdb` using an administrative SQL connection.
4. Verify the selected foundation models are active and available on demand in `eu-central-1`.
5. Run all local checks and inspect the complete Git diff and planned CloudFormation resources.

The deploy-time identifiers are CloudFormation parameters, while all permanent AWS behavior,
permissions, names, and environment configuration remain in `template.yaml`:

```powershell
sam deploy `
  --stack-name cockroach-agentic-memory-dev `
  --profile cockroach-hackathon-dev `
  --region eu-central-1 `
  --capabilities CAPABILITY_NAMED_IAM `
  --resolve-s3 `
  --parameter-overrides `
    EnvironmentName=dev `
    McpSecretArn=<secret-arn> `
    CockroachClusterId=<cluster-uuid> `
    CockroachDatabase=defaultdb
```

Do not commit resolved parameter values. A deployment is not complete until the three signed routes
have been smoke-tested and the investigation response references the synthetic stored incident.

## Security properties

- API Gateway keeps `AWS_IAM` as the default authorizer.
- The Lambda role can invoke only the two configured Bedrock foundation-model resources.
- `secretsmanager:GetSecretValue` is limited to the one supplied secret ARN.
- The repository exposes only `save` and scoped `find_similar`; MCP tools are allowlisted to
  `insert_rows` and `select_query`.
- Similarity SQL is constructed only inside the adapter from validated values. It is never supplied
  by the model or caller, and string values are escaped.
- Errors and health output redact dependency and credential details.

## Deferred work

The MVP does not include a Bedrock Converse tool loop, ingestion pipeline, frontend, streaming,
cross-region failover, or production-grade identity and tenant policy. See
[`docs/architecture.md`](docs/architecture.md) for operational limitations and extension points.
