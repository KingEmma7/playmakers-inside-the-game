# HANDOFF — current state (as of Wed 14 Oct 2026)

## TL;DR
- **Phase 1 (foundation) is done**, tested, and is what's in this repo.
- **Phase 2 (agents) crashed before committing.** Its code was recovered into `salvage/phase2/` as
  reference. It is *not* wired in, *not* tested. Restart Phase 2 using it as a head start.
- Previous builder (Cursor cloud agent) is out of usage; work continues in **Codex**.

## What exists and works (Phase 1)
| Area | Path | Status |
|---|---|---|
| Event contract | `packages/gallery_schema` | Pydantic `MatchEvent` + JSON Schema v1 (`schemas/v1/match_event.schema.json`), export script |
| Simulator | `packages/pitchsim` | Seeded 90-min match: passes, carries, shots+xG, tackles, fouls, cards, subs, goals, possession, positions; tactical styles (high press / counter / possession); scripted story events; ground-truth key-moment labels |
| Calibration | `pitchsim validate` | 50 matches: passes 1056.6 (900–1100), shots 20.3 (18–32), goals 3.16 (2.2–3.2), pass acc 0.815 (0.77–0.87), fouls 16.5 (15–35). **All OK** |
| Season dataset | `pitchsim season` | 380-match NDJSON.gz, gitignored |
| Replay API | `services/replay_api` | FastAPI `/healthz`, `/replay/sse`, `/replay/ws` (real-time or accelerated `speed`) |
| Agents | `packages/gallery_agents` | **Interfaces only** (`interfaces.py`: Protocols for 7 agents, `ViewerProfile`, `OverlayCue`) |
| Infra | `infra/` | `azure.yaml` + `main.bicep` stubs (Container Apps, Cosmos DB, Event Hubs). Never deployed |
| CI | `.github/workflows/ci.yml` | Python 3.12, ruff format/check, pytest |
| Tests | `tests/` | 3 tests (determinism, schema validity, calibration) — **pass** (re-verified 14 Oct, Python 3.13) |

Note: the original Cursor repo was a hidden draft and couldn't be fetched, so this tree was rebuilt
byte-for-byte from the build transcript's edit log; tests and calibration numbers match the original run
exactly. The only edit is `extend-exclude = ["salvage"]` in `pyproject.toml` so ruff ignores the salvage folder.

## What Phase 2 attempted (in `salvage/phase2/`)
- `packages/gallery_stats/` — deterministic `StatsEngine`: `possession`, `pressure_index`, `pass_difficulty`,
  `xg`, `momentum`, each returning Pydantic results with `Evidence` (event_ids).
- `services/stats_mcp/` — FastMCP server exposing those 5 tools (`ingest_event` too); also mounted into
  replay_api at `/stats-mcp`.
- `gallery_agents/contracts.py` — Pydantic `ViewerProfile`, `Insight`, `OverlayCue` (with
  `evidence_event_ids`, persona, language), `ComplianceDecision`.
- `gallery_agents/agents.py` — `StatsAgent`, `TacticsAgent`, `StorylineAgent`, `WhatIfAgent`,
  `ComplianceAgent`, `GraphicsAgent`, `Director` (deterministic/offline logic, `AgentFailure`).
- `gallery_agents/checkpointing.py` (`CheckpointManager`, `PipelineCheckpoint`), `state_store.py`
  (`InMemoryMatchStore`, `MatchState`), `pipeline.py` (`GalleryPipeline`, `GalleryPipelineConfig` with
  `kill_tactics_after_sequence`, `whatif_rollouts`), `personalize.py` (persona/favourite/Spanish shaping —
  a tiny phrase table; should become LLM translation with mock fallback).
- `gallery_agents/model_clients.py` — `DeterministicMockChatClient`, `AzureOpenAIChatClient`,
  `FoundryOpenAICompatChatClient` (all subclass Agent Framework `BaseChatClient`), `create_gallery_chat_client()`
  picks by env vars.
- `pitchsim/whatif.py` — `MatchSnapshot`, `snapshot_from_events`, `rollout_from_snapshot`,
  `win_probability_delta_for_forced_goal`. `pitchsim/story.py` — load story scripts (YAML).
- `replay_api/main.py` — adds `/gallery/sse` and `/gallery/ws` streaming personalised overlay cues
  (params: seed, speed, persona, language, favourites, kill flag).
- `tests/test_gallery_pipeline.py` — kill→fallback→recover and Spanish What-If tests.

### Known issues in the salvage (fix when porting)
1. `pipeline.py`: `@dataclass(frozen=True)` with `home_style: TeamStyle = TeamStyle(...)` → **ValueError
   (mutable default)**. Use `field(default_factory=...)`.
2. `gallery_agents/pyproject.toml` pins `openai>=1.40,<2` → **conflicts** with agent-framework-devui
   (openai>=2.45) and azure-ai-projects 2.7 (openai>=3). Remove the pin (verified: `pip check` clean without it).
3. 26 ruff lint errors (mostly import order; `ruff check --fix`).
4. The "agents" are still mostly deterministic Python; they are not yet real Agent Framework
   `Agent`/`WorkflowBuilder` executors, and LLM agents don't actually call the MCP tools. Phase 2 must
   make the workflow + MCP tool calls real (with mock client offline).
5. Checkpointing is in-memory; Agent Framework has `CheckpointStorage` / `FileCheckpointStorage` /
   `WorkflowBuilder.with_checkpointing(...)` — use it (file storage now, Cosmos later).

## Decisions made
- Project: **Gallery**, with **What-If Lab folded in** as the `what_if` agent; add MatchDesk-style
  **Foundry eval gate in CI** and the **season dataset**.
- Category: Best Multi-Agent System.
- Python monorepo with editable packages; FastAPI; SSE + WS; Pydantic contracts; ruff; pytest.
- Offline-first: mock model client so CI/demo runs without Azure.
- Fictional clubs/players only.
- Code lives in Cursor's repo first → **moving to a public GitHub repo now** (`gallery-inside-the-game`).

## Open questions / needs from King Emmanuel
- Azure subscription with credits (free account gives $200 / 30 days) — needed from Phase 4 (~20 Oct).
- Foundry project + a model deployment (e.g. a small GPT model) — Phase 4.
- Video recording tool (OBS is free) and a YouTube account — Phase 5.
