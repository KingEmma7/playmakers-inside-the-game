# Azure scaffolding (Phase 1 stub)

This directory contains **non-deployed** Azure Developer CLI (`azd`) + Bicep stubs for the planned
Playmakers architecture:

- Azure Container Apps (ACA)
- Cosmos DB (blackboard store)
- Event Hubs (match event ingestion)

Phase 1 does not deploy anything and requires **no credentials**.


## Local containers (Phase 4 preparation)

From the repository root: `docker compose up --build`. Open http://localhost:5173;
the API is on http://localhost:8000. Stats MCP runs inside the API at `/stats-mcp/`.
The API uses one worker so in-memory sessions can be shared. Both images use
multi-stage builds; the API runs non-root. The web container writes `config.js`
from `API_BASE` (default `/api`) and nginx proxies that path to the API without SSE
buffering. Set `CORS_ORIGINS` for web clients on a different origin. No credentials
are required. These Dockerfiles do not change the undeployed Bicep stubs above.
