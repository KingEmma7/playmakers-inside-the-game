# Azure template (azd + Bicep)

Not deployed yet. Validated locally with `az bicep build`, `az bicep lint` and `azd show`.

`main.bicep` (subscription scope) creates `rg-playmakers-demo` in `eastus2`, and
`resources.bicep` creates inside it:

| Resource | Setting |
| --- | --- |
| Foundry account (`Microsoft.CognitiveServices/accounts`, kind AIServices, S0) | custom subdomain, local (key) auth disabled |
| Foundry project `proj-playmakers` | endpoint passed to the API as `AZURE_AI_PROJECT_ENDPOINT` |
| Model deployment `gpt-41-mini` | gpt-4.1-mini 2025-04-14, GlobalStandard, capacity from `azd env set PLAYMAKERS_MODEL_CAPACITY` (default 50 = 50K TPM, clamped to 1–100), no auto-upgrade |
| Log Analytics `log-playmakers` | PerGB2018, 30-day retention, 0.2 GB/day cap |
| Application Insights `appi-playmakers` | workspace-based; connected to the Foundry account for the Tracing view |
| User-assigned identity `id-playmakers` | Azure AI User + Cognitive Services OpenAI User on the Foundry account only (+ Speech User when `PLAYMAKERS_ENABLE_SPEECH=true`) |
| Developer roles | the same two roles for `AZURE_PRINCIPAL_ID` (set by azd), for local runs |
| Container Apps environment `cae-playmakers` | Consumption only: no workload profiles, VNet or planned maintenance |
| `ca-playmakers-api` | GHCR image, 1 vCPU / 2 GiB, min 0 / max 1 replica (in-memory sessions), `/healthz` probes |
| `ca-playmakers-web` | GHCR image, 0.25 vCPU / 0.5 GiB, min 0 / max 1, `API_BASE` = API URL, `API_UPSTREAM` empty |

The API gets `AZURE_CLIENT_ID`, `APPLICATIONINSIGHTS_CONNECTION_STRING`,
`STATS_MCP_URL=http://127.0.0.1:8000/stats-mcp/`, `WHATIF_WORKERS=1`, `CORS_ORIGINS` = the
web URL, and the live-match caps (2 concurrent, 15 per day). There is no Cosmos DB, Event
Hubs, Key Vault or container registry.

Run from this directory: `azd env new playmakers-demo --location eastus2`, then `azd up`.
Outputs include `WEB_URL` and `API_URL`. Teardown: `azd down --purge`.

## Local containers

From the repository root: `docker compose up --build`. Open http://localhost:5173;
the API is on http://localhost:8000. Stats MCP runs inside the API at `/stats-mcp/`.
The API uses one worker so in-memory sessions can be shared. Both images use
multi-stage builds; the API runs non-root. The web container writes `config.js`
from `API_BASE` (default `/api`) and nginx proxies that path to `API_UPSTREAM`
(default `http://api:8000`) without SSE buffering. Set `CORS_ORIGINS` for web clients on
a different origin. No credentials are required.
