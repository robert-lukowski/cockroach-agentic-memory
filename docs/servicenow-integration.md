# ServiceNow integration contract

## Boundary and authentication

The ServiceNow scoped application sends `POST /servicenow/analyze` with `Content-Type:
application/json` and the dedicated API Gateway key in `x-api-key`. That route overrides the REST
API's default IAM authorizer. `GET /health`, `POST /incidents`, and `POST /investigations` retain the
default `AWS_IAM` authorizer and do not accept the ServiceNow key as a substitute for SigV4.

The generated key is associated with a development usage plan set to 1 request/second, burst 2, and
100 requests/day. The key value is handled only in AWS and ServiceNow private configuration; it is
not a CloudFormation parameter, environment variable, log field, or repository value.

## Request

The request must be a JSON object no larger than 32 KiB containing exactly these string fields:

| Field | Required value | Maximum characters |
| --- | --- | ---: |
| `incident_sys_id` | 32 hexadecimal characters | 32 |
| `number` | non-empty | 40 |
| `short_description` | non-empty | 256 |
| `description` | may be empty | 8,000 |
| `category` | may be empty | 128 |
| `subcategory` | may be empty | 128 |
| `priority` | may be empty | 32 |
| `impact` | may be empty | 32 |
| `urgency` | may be empty | 32 |
| `assignment_group` | may be empty | 256 |
| `cmdb_ci` | may be empty | 256 |
| `opened_at` | may be empty | 64 |

Every key is present in the real `AgenticMemoryClient` payload, including fields whose current value
is empty. Missing, extra, non-string, or over-limit values return the standard safe `400`
validation envelope. The request has no `scope`, SQL, model, tool, or retrieval-control field.

The handler excludes `incident_sys_id` from embedding text and turns the populated display fields
into a deterministic symptoms document. It constructs an internal `InvestigationRequest` with the
deployment-owned scope, no service/environment filter, and `top_k=5`.

## Success response

Status `200`:

```json
{
  "recommendation": "Review the matching incident evidence and inspect connection saturation.",
  "supporting_incident_ids": ["11111111-1111-4111-8111-111111111111"]
}
```

`recommendation` is non-empty model output grounded in retrieved evidence. Incident IDs are copied
from validated repository results and cannot be supplied by the model. The response intentionally
omits the backend `evidence` detail because the existing ServiceNow parser needs only the two fields
above.

Expected adapter failures use the existing safe `502` error envelope. The ServiceNow client treats
non-2xx responses, invalid JSON, or a missing recommendation as failure and writes work notes only
after a successful parsed response.

## Data and logging rules

Analyzing an active ServiceNow incident performs retrieval and generation only; it does not create
an incident memory. Resolved history remains an explicit `POST /incidents` workflow. Logs contain
request IDs and stable error categories, never request bodies, descriptions, keys, model responses,
SQL, or MCP provider data.
