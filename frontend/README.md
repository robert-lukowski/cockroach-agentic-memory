# Agentic Incident Command Center

This Streamlit application calls the existing API-key-protected `POST /servicenow/analyze`
endpoint. It does not connect directly to AWS, Bedrock, Managed MCP, CockroachDB, or ServiceNow.
Rich investigation responses are visualized as a star-shaped Operational Memory Graph containing
only the current incident and the historical incidents actually returned by vector retrieval.

The public UI is browseable without authentication, but live investigation calls are protected by a
small Streamlit-session judge gate. The gate is a demo/cost-control layer rather than a replacement
for production identity and access management. It does not change the ServiceNow integration path.

## Local setup

From the repository root, install the existing development dependencies and the frontend package:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pip install -r frontend\requirements.txt
```

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it locally. Never commit
the populated file.

```toml
AGENTIC_MEMORY_API_ENDPOINT = "https://example.execute-api.eu-central-1.amazonaws.com/v1/servicenow/analyze"
AGENTIC_MEMORY_API_KEY = "replace-locally"
AGENTIC_MEMORY_REQUEST_TIMEOUT_SECONDS = "45"
JUDGE_PIN_SHA256 = "replace-with-a-64-character-sha256-digest"
```

`AGENTIC_MEMORY_API_ENDPOINT` must be the full existing `/servicenow/analyze` HTTPS URL. The timeout
is optional and must be between 1 and 120 seconds. The API client configuration can also be supplied
through its existing environment variables; environment variables take precedence over Streamlit
secrets for those API settings.

`JUDGE_PIN_SHA256` is intentionally read from Streamlit secrets only. Store the SHA-256 digest, not
the raw PIN. The exact PIN string is hashed without trimming, so leading zeroes remain significant.
One safe way to generate the digest locally without echoing the PIN is:

```powershell
python -c "import getpass,hashlib; p=getpass.getpass('Judge PIN: '); print(hashlib.sha256(p.encode()).hexdigest())"
```

If the hash secret is missing or malformed, the app fails closed: scenarios and architecture remain
browseable, but the live investigation button stays disabled. A correct PIN unlocks only the current
Streamlit session. The PIN and its hash are not added to the analysis payload or sent to API Gateway,
Lambda, Bedrock, CockroachDB, or ServiceNow.

Run the frontend from the repository root:

```powershell
.venv\Scripts\python.exe -m streamlit run frontend\app.py
```

The UI displays backend timing and Privacy Guard metadata when returned by the deployed analysis
service. It separately labels the measured client round-trip time and never fabricates missing
backend timing fields.
