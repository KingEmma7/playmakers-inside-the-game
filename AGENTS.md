# AGENTS.md — instructions for coding agents (Codex, Copilot, etc.)

Read this file fully before changing anything. Then read `docs/HANDOFF.md` (current state) and
`docs/PLAN.md` (what to build next, phase by phase).

## 1. Project goal

**Playmakers** is an AI production crew for football. Specialised AI agents
(Director, Stats, Tactics, Storyline, Graphics, Compliance, What-If, Audience/Personalizer) watch a
live **synthetic** match event stream and produce:

1. timed, broadcast-safe **overlay cues** (Overlay Timeline JSON) rendered next to the match, and
2. a **personalised second-screen feed** per viewer (Analyst vs Casual fan, favourite club/player, language).

Signature demo moments (these must work on camera):
- **Kill & recover:** kill the Tactics agent mid-match → graphics fall back to deterministic templates
  within one event → the agent restarts from its checkpoint and catches up.
- **What-If:** at a key moment (goal, big chance) the what_if agent re-simulates N alternatives with
  PitchSim (parallel) and shows the win-probability delta with a short explanation.
- **Same moment, two audiences:** analyst view and casual/favourite-player/Spanish view side by side.

Built for the **Microsoft x Premier League "Inside the Game" hackathon** (solo entrant).
Target category: **Best Multi-Agent System** (also eligible for Grand Prize).

## 2. Hackathon rules that constrain the code (non-negotiable)

- Submission closes **27 Oct 2026, 11:59pm PT (= 28 Oct 06:59 GMT)**. Internal target: **submit Mon 26 Oct**.
- **Synthetic, football-realistic data only.** No real match data/footage. **Fictional clubs and players
  only. No Premier League names, logos, crests, fonts, or marks anywhere** (code, data, UI, video).
- Repo must be **public on GitHub**, in **English**, original work, MIT licensed.
- Judges need a **working demo link** (public URL; if login is needed, document credentials).
- Demo video **< 2 minutes**, public on YouTube/Vimeo, shows the project actually running, **no copyrighted music**.
- Elevator pitch: what it is, which Microsoft/Azure tech, what it does, what problem it solves.
- Judges may score mostly from the README + video, so the README must be excellent.

### Judging (20% each) — every change should push at least one of these
1. **Technological Implementation** (also the **first tie-breaker**): creativity and *optimized synthetic
   data creation* (PitchSim calibration, season dataset, planted ground-truth moments), quality software
   practices (tests, CI, typed contracts, IaC).
2. **Agentic Design & Innovation:** distinct agent roles, MCP tools, handoffs, checkpointing,
   failure recovery, verifier loop (Compliance), evals.
3. **Real-World Impact:** mirrors real broadcast graphics workflow (cue sheet, safe areas, approvals);
   production-readiness (observability, fallbacks, cost/latency budget).
4. **UX & Presentation:** broadcast-quality overlay UI, visible agent trace, clear 2-minute video.
5. **Category Adherence:** visibly uses hero tech — **Microsoft Foundry, Microsoft Agent Framework,
   MCP (custom stats MCP + Azure MCP Server), GitHub Copilot, Azure Container Apps, Azure Cosmos DB**.

## 3. Architecture (target)

```
PitchSim (synthetic events) ──► replay_api (FastAPI: SSE/WS) ──► ingest ──► Match State store (in-memory → Cosmos DB)
                                                                          │
                     Director (Agent Framework workflow, latency budget, checkpointing)
                       ├─ Stats agent ──(MCP)──► stats_mcp (deterministic tools: possession, pressure_index,
                       │                                       pass_difficulty, xg, momentum)
                       ├─ Tactics agent (LLM)       ├─ Storyline agent (LLM, long-horizon arcs)
                       ├─ What-If agent (PitchSim rollouts, parallel)
                       ├─ Compliance agent (code + small LLM: every number checked by event_id)
                       ├─ Graphics agent (schema-validated OverlayCue JSON; template fallback)
                       └─ Audience/Personalizer (fan-out per ViewerProfile)
                                   │
                         /playmakers/sse, /playmakers/ws  ──► web/ (React + Vite overlay UI, agent trace panel)
Azure: Container Apps (api, stats-mcp, web), Cosmos DB (state + checkpoints), Foundry (models, evals,
tracing → App Insights), azd + Bicep in infra/, GitHub Actions CI with a Foundry eval gate.
```

Model access is **pluggable**: Azure OpenAI / Foundry when env vars are set; a **deterministic offline mock
client** otherwise. Everything (tests, CI, local demo) MUST run with **no credentials**.

## 4. Repository layout

```
packages/playmakers_schema/   Versioned MatchEvent contract (Pydantic + JSON Schema v1). Shared by all.
packages/pitchsim/         Seeded simulator, calibration validator, replay generator, season dataset.
packages/playmakers_agents/   Agents (Phase 1 = interfaces only; Phase 2 builds the real thing).
services/replay_api/       FastAPI: /healthz, /replay/sse, /replay/ws (Phase 2 adds /playmakers/*).
infra/                     azd (azure.yaml) + Bicep stubs: Container Apps, Cosmos DB, Event Hubs. Not deployed yet.
tests/                     pytest: determinism, schema validity, calibration.
salvage/phase2/            REFERENCE ONLY: uncommitted Phase 2 code recovered from a crashed run.
                           Not installed, not linted, not tested. Port pieces into the real tree; don't import from here.
docs/                      HANDOFF.md (state), PLAN.md (phased plan + prompts).
```
Planned additions: `packages/playmakers_stats/`, `services/stats_mcp/`, `web/` (React/Vite), `evals/`.

## 5. Commands

```bash
python3 -m venv .venv && source .venv/bin/activate        # Python 3.12+ (3.13 also works)
python -m pip install -U pip
python -m pip install -r requirements-dev.txt
python -m pip install -e packages/playmakers_schema -e packages/pitchsim -e packages/playmakers_stats -e services/stats_mcp -e services/replay_api -e packages/playmakers_agents
ruff format --check . && ruff check .                     # lint (ruff 0.17.0, pinned)
pytest                                                    # tests
python -m pitchsim validate --matches 50                  # calibration report (all lines must say OK)
python -m pitchsim simulate --seed 7                      # one match as JSON lines
python -m pitchsim season --matches 380 --seed 0          # season dataset → data/ (gitignored)
uvicorn replay_api.main:app --reload --port 8000          # then: curl -N "localhost:8000/replay/sse?seed=7&speed=10"
```
When you add a package, add its `pip install -e` line to **both** this section and `.github/workflows/ci.yml`.

## 6. Conventions & coding standards

- Python 3.12 syntax, full type hints, `from __future__ import annotations`.
- Pydantic v2 models for every contract crossing a boundary (agents, API, MCP, storage). Version schemas.
- Deterministic by default: every random source takes a seed. Same seed ⇒ same output (tests enforce this).
- Dataclasses: **never** use a mutable/instance default (e.g. `TeamStyle()`); use `field(default_factory=...)`.
- Agents cite evidence: every insight/overlay carries `evidence_event_ids`; Compliance rejects cues without them.
- Stats are **pure deterministic code** exposed via MCP; LLM agents never invent numbers.
- Keep LLM calls behind the model-client interface; tests use the mock client only.
- Async (`asyncio`) for the pipeline and streaming; no blocking calls in the event loop
  (use `ProcessPoolExecutor`/`asyncio.to_thread` for What-If rollouts).
- Small, focused commits with conventional messages (`feat(agents): ...`, `fix(api): ...`, `test: ...`).
- Frontend (Phase 3): TypeScript, React + Vite, no UI kit with sports branding; types generated or mirrored
  from the Pydantic/JSON Schema contracts.

## 7. Dependency pitfalls (learned the hard way — read before installing anything)

- The PyPI package `agent-framework` is a meta package; the importable code is
  **`agent-framework-core`** (`import agent_framework`). Install `agent-framework-core` directly and
  avoid `[all]` extras unless needed.
- **Do NOT pin `openai<2`.** Agent Framework / `azure-ai-projects` need a newer openai (2.x/3.x). That pin
  is what broke the previous Phase 2 run. Let the resolver choose, then run `pip check`.
- Agent Framework 1.21 needs **`mcp<2`** (use `mcp>=1.24,<2`, tested with 1.30.0).
- In `mcp` 1.x, `streamablehttp_client` is deprecated → use `streamable_http_client`.
  Server side: `from mcp.server.fastmcp import FastMCP`; `FastMCP.streamable_http_app()` can be mounted in FastAPI.
- `ruff==0.12.14` does not exist on PyPI; repo pins `ruff==0.17.0`.
- Always run `pip check` after changing dependencies. CI must install from a clean venv.

## 8. Definition of done (for every task)

- [ ] `ruff format --check .` and `ruff check .` pass.
- [ ] `pytest` passes **offline with no env vars/credentials**; new behaviour has tests.
- [ ] `python -m pitchsim validate --matches 50` still all OK (if simulator touched).
- [ ] CI workflow updated for any new package; `pip check` clean.
- [ ] README / docs updated (run instructions, architecture, what needs Azure).
- [ ] No secrets, keys, connection strings, or `.env` committed (use `.env.example` with placeholders).
- [ ] Only fictional clubs/players; no Premier League marks.
- [ ] Summarise what changed, how to run it, and anything left undone in the final message / PR description.

## 9. Secrets & config

Read config from env vars only, e.g. `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`,
`AZURE_AI_PROJECT_ENDPOINT`, `COSMOS_ENDPOINT`. Prefer `DefaultAzureCredential` (managed identity in
Container Apps) over keys. Never print secrets in logs. Keep `.env` gitignored.
