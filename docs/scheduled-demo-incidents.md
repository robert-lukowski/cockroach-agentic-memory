# Scheduled demo incidents

The scheduled workflow creates one new active, fictional ServiceNow incident every six hours. It
uses only the ten active templates in `data/servicenow_demo_incidents.json`; resolved records are
never selected. Manual runs may choose a stable cluster with `--scenario`, while scheduled runs
select one active cluster for each invocation.

## Schedule and execution

`.github/workflows/generate-demo-incident.yml` runs at `00:00`, `06:00`, `12:00`, and `18:00` UTC
and also supports `workflow_dispatch`. A concurrency group prevents overlapping runs. The workflow:

1. obtains a short-lived GitHub OIDC token;
2. assumes the repository-specific AWS role;
3. retrieves exactly one JSON secret from Secrets Manager in `eu-central-1` into a mode-600 runner
   temporary file;
4. creates one active incident through the ServiceNow Table API; and
5. deletes the temporary file on exit.

It does not use static AWS keys or GitHub Secrets. It prints only the scenario, mode, caller mode,
caller resolution boolean, HTTP status, and created incident number. Credentials, headers,
request/response bodies, incident descriptions, names, usernames, email addresses, sys_ids, and
provider details are never printed.

## Required repository variables

- `AWS_OIDC_ROLE_ARN`: ARN output by `infrastructure/github-actions-oidc.yaml`.
- `SERVICENOW_SECRET_ID`: name or ARN of the single ServiceNow credential secret.

The Secrets Manager value must be one JSON object:

```json
{
  "SERVICENOW_INSTANCE_URL": "https://<pdi-host>",
  "SERVICENOW_USERNAME": "<integration-user>",
  "SERVICENOW_PASSWORD": "<protected-password>",
  "SERVICENOW_CALLER_MODE": "fixed",
  "SERVICENOW_CALLER_USER_NAME": "<active-user-name>"
}
```

`SERVICENOW_CALLER_MODE` defaults to `fixed`. Fixed mode requires
`SERVICENOW_CALLER_USER_NAME`; the generator performs an exact active `user_name` lookup and fails
unless exactly one record matches. In `random` mode the username setting is ignored. The hackathon
workflow sets `SERVICENOW_CALLER_MODE=random` as non-secret job configuration, so the existing
secret does not need caller fields for scheduled runs.

Do not store this JSON in GitHub, workflow YAML, repository variables, command history, or files in
the repository.

## Incident safety

Every generated incident is active and contains `[AGENTIC_MEMORY_SCHEDULED_DEMO]` exactly once. A
new UUID correlation ID is generated for every invocation and sent in the standard ServiceNow
`correlation_id` field. The payload never includes root cause, resolution, close notes, resolved
time, or close code. Assignment group and CI references are intentionally empty; the generator does
not create reference records.

Caller resolution always completes before incident creation. Random mode queries active users with
a non-empty `user_name`, excludes web-service-only users and obvious service, API, bot, automation,
system, and integration accounts, and selects one eligible sys_id with `secrets.choice`. If no
eligible caller exists, the run fails before the incident POST. Identity fields are never logged.

TLS certificate verification is enabled and every request has a 20-second timeout. HTTP 429 and
transient 5xx responses are retried at most twice after the initial request. HTTP 400, 401, and 403
are never retried. A PDI returning 502 therefore causes one bounded failed workflow rather than an
unbounded loop.

Run a deterministic local preview without AWS or ServiceNow access:

```powershell
$env:SERVICENOW_CALLER_MODE = "random"
.venv\Scripts\python scripts\generate_scheduled_incident.py `
  --scenario connect-outbound `
  --dry-run
Remove-Item Env:SERVICENOW_CALLER_MODE
```

## OIDC infrastructure

Read-only inspection on 2026-08-06 found no GitHub OIDC provider, GitHub-trusted IAM role, or
ServiceNow-named secret in the development account. `infrastructure/github-actions-oidc.yaml`
therefore prepares, but does not deploy, one provider and one role. The role is restricted to the
`main` branch of `robert-lukowski/cockroach-agentic-memory`. Because this repository uses GitHub's
immutable OIDC subject format, the trust condition also pins the owner and repository numeric IDs.

The resulting trust policy is exactly:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::<AWS_ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:robert-lukowski@207513888/cockroach-agentic-memory@1322917399:ref:refs/heads/main"
      }
    }
  }]
}
```

Its only identity permission is:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "secretsmanager:GetSecretValue",
    "Resource": "<ServiceNowSecretArn parameter>"
  }]
}
```

The secret must use the AWS-managed Secrets Manager key for the role to remain limited to that one
action. A customer-managed KMS key would require a separately reviewed `kms:Decrypt` permission.
Do not deploy the template until the secret exists and its exact ARN is approved.
