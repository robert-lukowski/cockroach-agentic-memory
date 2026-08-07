# Agentic Incident Command Center

This Streamlit application calls the existing API-key-protected `POST /servicenow/analyze`
endpoint. It does not connect directly to AWS, Bedrock, Managed MCP, CockroachDB, or ServiceNow.
Rich investigation responses are visualized as a star-shaped Operational Memory Graph containing
only the current incident and the historical incidents actually returned by vector retrieval.

## Local setup

From the repository root, install the existing development dependencies and the frontend package:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pip install -r frontend\requirements.txt
```

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it locally, or provide
the same names as process environment variables. Never commit the populated file.

```toml
AGENTIC_MEMORY_API_ENDPOINT = "https://example.execute-api.eu-central-1.amazonaws.com/v1/servicenow/analyze"
AGENTIC_MEMORY_API_KEY = "replace-locally"
AGENTIC_MEMORY_REQUEST_TIMEOUT_SECONDS = "45"
```

`AGENTIC_MEMORY_API_ENDPOINT` must be the full existing `/servicenow/analyze` HTTPS URL. The timeout
is optional and must be between 1 and 120 seconds. Environment variables take precedence over
Streamlit secrets.

Run the frontend from the repository root:

```powershell
.venv\Scripts\python.exe -m streamlit run frontend\app.py
```

The current backend does not return confidence or server timings, so those values appear only when
present in a compatible future response. The UI separately labels its measured client round-trip
time and never fabricates missing backend timing fields.
