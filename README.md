# Gallery — “Inside the Game” Hackathon (Microsoft x Premier League)

**Gallery** is a multi-agent “virtual broadcast production gallery” that turns a live football match event stream into explainable, timed overlay cues and personalized audience output.

This repository is being built for the **Microsoft x Premier League “Inside the Game” developer hackathon**. It uses **synthetic, football-realistic data only**, with **fictional clubs and players** (no Premier League marks).

## Phase 1 (this repo state)

Phase 1 ships the foundation:

- **PitchSim**: a deterministic, seeded match-event simulator that produces a full 90-minute match as a timestamped event stream.
- **Shared contracts**: a typed, versioned event schema (JSON Schema + Pydantic).
- **Streaming replay**: a FastAPI service that replays a simulated match over **SSE** or **WebSocket**, in real-time or accelerated (e.g. 10×).
- **Azure-ready stubs**: `azd` + Bicep placeholders for Container Apps, Cosmos DB, Event Hubs (not deployed; no credentials required).
- **CI**: lint + tests run on GitHub Actions.

## Pipeline fit (hackathon brief)

The hackathon asks for a single pipeline with five stages:

- **Ingest**: Phase 1 replays events via SSE/WS (Phase 2 will add Event Hubs ingestion).
- **Interpret**: Phase 1 emits calibrated match events + ground-truth labels (Phase 2 stats/tactics tools/agents build on this).
- **Explain**: placeholder agent interfaces only (Phase 2).
- **Render**: Phase 1 emits machine-readable events suitable for overlay cue generation (Phase 2 overlay-timeline schema + renderer).
- **Personalize**: placeholder agent interface only (Phase 2).

## Architecture (Phase 1 + stubs)

```mermaid
flowchart LR
  subgraph Local Dev (Phase 1)
    PitchSim[PitchSim\nPython simulator] -->|MatchEvent v1 stream| API[Replay API\nFastAPI SSE + WS]
    API --> Client[CLI / curl / browser consumer]
  end

  subgraph Azure (planned scaffolding)
    EventHubs[(Event Hubs)] --> Ingest[Ingest worker\n(Container Apps)]
    Ingest --> Cosmos[(Cosmos DB\nMatch blackboard)]
    Cosmos --> Agents[Gallery agents\nDirector/Stats/Tactics/...]
  end

  PitchSim -. future transport .-> EventHubs
```

## Repo layout

- `packages/gallery_schema/`: versioned event contracts (JSON Schema + Pydantic models)
- `packages/pitchsim/`: simulator + validation CLI (`python -m pitchsim ...`)
- `services/replay_api/`: FastAPI SSE/WS replay endpoints
- `packages/gallery_agents/`: placeholder packages/interfaces for future agents (no LLM calls yet)
- `infra/`: `azd` + Bicep stubs for Azure resources

## Quickstart (local)

Prereqs: **Python 3.12+**

```bash
cd /path/to/repo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip

# dev tooling
python -m pip install -r requirements-dev.txt

# editable installs (monorepo)
python -m pip install -e packages/gallery_schema
python -m pip install -e packages/pitchsim
python -m pip install -e services/replay_api
python -m pip install -e packages/gallery_agents
```

### Calibration report (must be within targets)

```bash
python -m pitchsim validate --matches 50
```

### Season-scale synthetic dataset (optional)

Generate a season-like dataset (newline-delimited JSON; output is gitignored by default):

```bash
python -m pitchsim season --matches 380 --out data/season.match_events.jsonl.gz
```

### Live replay (SSE)

Start the API:

```bash
uvicorn replay_api.main:app --reload --port 43123
```

In another shell, connect via SSE (example: 10× speed):

```bash
curl -N "http://127.0.0.1:43123/replay/sse?seed=123&speed=10"
```

### Live replay (WebSocket)

```bash
websocat "ws://127.0.0.1:43123/replay/ws?seed=123&speed=10"
```

## Notes

- **Synthetic-only**: no real match data, no Premier League marks.
- **Deterministic numbers**: downstream explanation agents must cite event IDs; no invented stats.

