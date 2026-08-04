# Agentic Incident Memory

Backend scaffold for an incident-troubleshooting application built for the CockroachDB × AWS
Hackathon. The application turns resolved incidents into reusable memory and retrieves similar
incidents before asking a generation model for a recommendation.

## Current status

The repository implements the first two local-only phases:

- Python 3.13 Lambda and API Gateway request handling.
- Strict request validation and response models.
- Deterministic RAG orchestration behind Bedrock and repository interfaces.
- Test-only Bedrock and mocked MCP repository adapters.
- A fail-closed default runtime with no network, database, secret, or credential access.
- AWS SAM infrastructure scaffolding with IAM-authenticated routes.

Live Bedrock, CockroachDB, and Managed MCP adapters are intentionally not implemented. Apart from
`GET /health`, the default Lambda handler returns `503 dependency_unavailable` until those adapters
are separately reviewed and approved.

## MVP API

### `POST /incidents`

Validates a resolved incident, requests a 1,024-dimensional embedding through the Bedrock port, and
stores it through the repository port. See [`events/create-incident.json`](events/create-incident.json).

### `POST /investigations`

Embeds submitted symptoms, retrieves similar incidents through the repository port, and provides
that evidence to the Bedrock generation port. Supporting incident IDs are derived from repository
results rather than model-generated text. See [`events/investigate.json`](events/investigate.json).

### `GET /health`

Returns process and configuration status. It reports only booleans and non-sensitive metadata; it
does not return model IDs, secret values, credential state, or environment contents.

## Architecture

The current and planned boundaries are documented in [`docs/architecture.md`](docs/architecture.md).
S3, file ingestion, a frontend, the Bedrock Converse tool loop, and live external adapters are
deferred beyond this scaffold.

## Local development

Prerequisites:

- Python 3.13
- AWS SAM CLI for template validation and local builds

PowerShell setup:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

Run local checks:

```powershell
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pytest
sam validate --lint --region eu-central-1
sam build
```

These tests inject deterministic fakes and make no network calls. `sam build` writes generated
artifacts under the ignored `.aws-sam/` directory. No deploy command is part of this phase.

## Planned stack

- Python 3.13
- AWS Lambda
- Amazon API Gateway
- Amazon Bedrock
- AWS SAM
- CockroachDB Cloud
- CockroachDB Managed MCP Server
- CockroachDB Distributed Vector Indexing

AWS development configuration is governed by [`AGENTS.md`](AGENTS.md). Never commit secrets or
deploy without the validation, diff review, resource review, and explicit approval required there.
