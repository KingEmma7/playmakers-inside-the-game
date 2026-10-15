# HANDOFF — current state (as of Wed 14 Oct 2026)

## Final Calm polish and worker lifecycle (15 Oct 2026)

- Favourite pitch chip counts actual observed shots, falling back to passes/touches or the
  player name before any involvement. About hides replay controls and centres a 720px text
  column in the shared full-content card (maximum 1392px).
- Dominance strips stretch from a consistent label column within card padding; the What-If
  before tick sits above the after fill.
- API lifespan owns one shared spawn-based What-If pool, capped at three workers per API
  process. Shutdown waits for running batches and cancels queued futures. Stream cancellation
  cancels its queued rollouts and explicitly closes its Director; already executing batches
  finish normally. CLI Directors retain ownership of their standalone pool.
- Validation: 47 offline Python tests, 9 frontend tests, Ruff format/check, frontend lint/build,
  pip check and the live screenshot flow pass. Captures refreshed in `web/shots/` and
  `web/e2e-screenshot.png`. No dependency changes or commits.

## Calm polish pass (15 Oct 2026)

- Inline label/value replay controls, fictional player names (Okafor by default), D safe-area
  shortcut, no floating session line; shared full-width Replay/About header and readable About list.
- Both audience cards retain their latest insight. Fan What-If persists after its on-air cue,
  keeps the actual rollout count, and includes a Spanish scenario, before/after bar and dominance.
  Evidence shows the last three cited IDs, with the complete list on hover.
- Analyst pitch chips retain the latest pass and shot. Metrics derive from received events:
  possession uses team-tagged event share, PPDA opposition passes per home defensive action,
  field tilt the home share of final-third pass entries. These are synthetic event proxies.
- Seeded staggered formations move with the ball; the followed player has a ring and a shot-count
  chip. Tactics failure displays Recovering/replaying and Graphics Fallback/template mode;
  actual caught-up traces restore Running. Stop remains disabled after the once-per-replay injection.
- Screenshot script waits for persistent What-If and Recovering, captures while Pause is visible,
  checks horizontal overflow and viewport clipping at 1440×900 and 1920×1080, then verifies
  both feeds' lifecycle history and About. API :8000 + Vite :5173; `cd web && npm run screenshot`.
- Validation: 44 offline Python tests, 7 frontend tests, Ruff format/check, frontend lint/build
  and pip check pass. Operator commits; no deployment or dependency changes.

## Calm restyle (15 Oct 2026)

- Entire web app now follows the Calm light direction: locally bundled Inter (SIL OFL),
  shared tokens in `web/src/tokens.css`, inline replay controls and Replay/About navigation,
  centred scoreboard, Analyst/For you cards, plain Agents status list, soft-red stop control,
  light pitch chips, What-If probability track, event-derived metrics/dominance and match timeline.
- Detailed storyline and handoff history remain available in expandable sections. Original
  stream/control accessibility names are preserved; visible button/status wording follows Calm.
- Fixed status aggregation: a rejected insight no longer overwrites a lifecycle fallback;
  the Agents list reflects failure in either audience feed. Recovery history survives the
  rolling recent-handoff window. Added a regression test.
- Verified frontend lint, **6 tests**, production build; backend Ruff format/check and
  **43 offline tests**, plus pip check. Live Chromium script passes with no page errors,
  mid-match content, pause/start, both feeds' recovery lifecycle and About navigation.
- Captures: `web/e2e-screenshot.png` (1920×1080), `web/shots/main.png`,
  `kill.png` and `about.png` (1440×900). Script checks horizontal overflow at both sizes.
  Run API :8000 and Vite :5173, then `cd web && npm run screenshot`; allow time to reach 20 minutes.
- No backend or dependency changes; no Azure deployment. Operator commits.

## TL;DR
- **Phase 3 is implemented**: React split view, typed SSE, broadcast overlays, trace, Chromium capture.
- **Phase 1 remains green**; baseline verified before implementation, including calibration,
  simulation, the 380-match season export and a replay SSE smoke check.
- **Phase 2A is implemented and green**: deterministic stats, streamable MCP, typed contracts,
  a real Agent Framework Director workflow and the offline CLI. No Azure credentials required.
- **Phase 2B is implemented**: recovery, seeded What-If, audience shaping, planted scripts and gallery streams.
- See the Phase 2B notes below for validation and limits.
- `salvage/phase2/` remains reference only. No installed code imports it.
- Commits could not be created in this workspace because `.git` is mounted read-only.

## Phase 3 implementation and validation (14 Oct 2026)

- `web/`: React 19 + Vite + TypeScript, ESLint, Vitest/Testing Library, Node 20 lockfile.
  `npm run types:generate` derives the three versioned TypeScript contracts from checked-in JSON Schemas;
  CI regenerates and checks for drift before lint/test/build. Generated files are ready for the operator to commit.
- Two independent personalised EventSources share the minimum received event sequence for display.
  Reconnect uses bounded exponential backoff and deduplicates replayed events/cues/traces. Full-time closes cleanly.
  Buffering covers one synthetic match; pause freezes the displayed program while streams continue.
- Canvas pitch, fictional SVG crests, ball interpolation, 22 formation-based dots, observed pass arcs;
  score/clock, safe guides, storyline/tactical lower thirds, momentum, pass-difficulty arc, xG shot card,
  favourite tags and What-If before/after/delta cards. Overlay selection uses match time, duration and priority.
- Seed/speed, fan Spanish/French and roster controls; agent handoffs/latencies/lifecycle status; failure injection
  in both feeds. New SSE `replay_from_ms` parameter rebuilds the deterministic prefix without replay delays,
  then resumes normal pacing at the requested minute. It preserves all events for correct score/evidence.
- `/about` distinguishes the running offline implementation from planned Azure deployment.
- PitchSim attaches applied scripted `style_changes` to the first subsequent event's ground truth.
  Snapshots reconstruct those styles plus red cards in order; supplied schedules support old recordings and
  future rollout changes. Continuations apply pending changes once, with deterministic tests.
- Validation: **43 Python tests**, Ruff format/check, pip check; 50-match calibration all five OK with
  unchanged means. **5 web tests**, lint and build pass. npm audit clean after updating Vitest.
- Chromium script `npm run screenshot` passed against the actual local API and Vite: personalised content,
  synced clocks, pause/start, Tactics down/caught-up, and `/about`, with no uncaught browser errors.
  Capture is `web/e2e-screenshot.png` (1920×1080). Run API :8000 + Vite :5173 first;
  restricted hosts can use `PLAYWRIGHT_BROWSERS_PATH=/tmp/gallery-playwright` for install/run.
- README documents setup, controls, screenshots, tests and limits. No commits made (operator commits).

Rough edges / Phase 4 boundaries:
- Default simulator has no full player tracking frames; formation-based player motion is explicitly labelled.
- Profile changes restart only the fan stream and temporarily hold the shared clock while it catches up.
  Seed/speed changes restart the match; Start after pause jumps to the buffered live position.
- Reconnect restarts ephemeral API sessions; no persistent resume. Failure injection is once per replay,
  reset via seed/speed. Large fast-forward prefixes still run the complete agent workflow and checkpoints.
- Casual offline wording uses the existing small phrase table; cloud models, Cosmos persistence,
  deployment, eval gates and observability remain Phase 4 work.

## Phase 2A implementation and validation (14 Oct 2026)

- `packages/gallery_stats`: six deterministic stats with Pydantic evidence, bounded event history,
  sequence/match validation, and inclusive time windows. Control vs chaos uses normalized entropy
  of completed directed pass edges and failed-pass share. Floating-point entropy is clamped to
  [0,1]. Nullable shot ground truth is handled safely; goals use required scoring_team_id.
- `services/stats_mcp`: FastMCP factory, `python -m stats_mcp` on port 8765 (`/mcp`), and
  replay API mount at `/stats-mcp/`, with explicit session-manager lifespan. Event unions are
  validated using TypeAdapter, not MatchEvent.model_validate. Tool outputs are Pydantic models.
- `gallery_agents/contracts.py`: Pydantic profiles, insights, cues, Compliance decisions and
  versioned trace events. Cues require evidence and include layer/safe_area. Overlay/trace schemas
  are exported by `python -m gallery_agents.export_schemas` into gallery_schema's v1 directory.
- `gallery_agents/workflow.py`: WorkflowBuilder Stats → fan-out Tactics/Storyline Agents →
  synchronized Compliance join → Graphics → Audience. Each executor emits traces. Compliance
  recomputes from stored event prefixes, verifies numeric metrics and prose against cited evidence,
  retries at most twice per insight and then templates. Audience stamps/fans out profiles only.
- `model_clients.py`: deterministic mock with streaming/non-streaming support; actual installed
  OpenAIChatCompletionClient for Azure and FoundryChatClient for Foundry, using DefaultAzureCredential.
  Live Stats invokes MCPStreamableHTTPTool, validates results against local evidence, and gives
  the explanation Agents read-only MCP functions. Live Azure calls have not yet been exercised.
- `state_store.py`: MatchStore Protocol and Pydantic MatchState backed by InMemoryMatchStore.
- Framework superstep checkpoints use FileCheckpointStorage with explicit Gallery type allowlists.
  Tests reload saved checkpoints. Complete match-store restoration/catch-up belongs to Phase 2B.
- Dependencies: agent-framework-core 1.21.0, agent-framework-openai 1.16.0,
  agent-framework-foundry 1.14.1, mcp>=1.24,<2 (resolved 1.30.0), openai resolved 3.31.0.
  No openai<2 constraint or framework meta-package. Real installed source APIs were inspected;
  checkpoint storage is a WorkflowBuilder constructor argument in this version.
- Validation: **31 offline tests pass** (including actual standalone/mounted HTTP MCP transport,
  Agent Framework MCP calls, verifier rejection/retry/fallback, fan-out, checkpoint reload,
  current JSON Schemas, client selection, deterministic cues and entropy boundary regressions).
  Ruff format/check and pip check pass. A separate clean Python 3.13 venv installs all packages
  and runs all tests. CI retains Python 3.12 and installs both new packages plus pip check.
- Full CLI command completed: `python -m gallery_agents demo --seed 7 --speed 50 --persona analyst`:
  1,569 events, **3,138 cues + 9,414 trace records**, with evidence, and file checkpoints.
  The framework emits two harmless mock-client function-invocation capability warnings to stderr.
  Stats tools run directly offline; the mock does not request function calls.

Run after root README editable installs:

```bash
python -m gallery_agents demo --seed 7 --speed 50 --persona analyst
python -m gallery_agents demo --seed 7 --speed 0 --limit 10
python -m stats_mcp
uvicorn replay_api.main:app --reload --port 8000
```

Phase 2B validation (14 Oct 2026):
- Phase 2A baseline: Ruff clean, 31 offline tests passed, demo CLI emitted cues/traces.
- Phase 2B: Ruff format/check and git diff whitespace checks clean; 40 offline tests pass.
- Clean Python 3.13 environment installs all packages and passes tests; pip check is clean.
- PitchSim validation: all five calibration checks OK across 50 matches (unchanged baseline).
- Full CLI `--seed 7 --speed 50 --persona analyst --kill tactics@20 --whatif-rollouts 200`:
  3,147 cues, 9,428 traces, one same-event fallback cue, all four required recovery steps,
  nine What-If cards. What-If wall latency 33–1,142ms in this run; all cues have evidence.
- Separate initial 200-rollout first-goal benchmark: 1.70s including process startup.

Phase 2B implementation:
- `checkpointing.py`: versioned recovery state behind `RecoveryStorage`, backed by the actual
  Agent Framework `CheckpointStorage` protocol / FileCheckpointStorage. Captures match event
  history and each writer's successful sequence. `Director.restore(match_id)` rebuilds shared
  state and StatsEngine in a fresh Director. Workflow superstep checkpoints remain enabled.
- Tactics kill injection (`--kill tactics@20`, API `kill=tactics@20`), deadlines (Tactics 4s,
  Graphics 1.5s), circuit breaker with bounded exponential event backoff, same-event templates,
  recreated Agent and verified replay of missed events. Recovery traces use the required names.
- `pitchsim/whatif.py` ports snapshot + event-model continuation; `what_if.py` runs before,
  after and counterfactual scenarios in a 3-worker ProcessPoolExecutor using paired seeds.
  Default N=200 per scenario; tests use N=20. First seed-7 goal benchmark: 1.70s including startup.
  Metrics have home-side win/draw/loss distributions and win_prob_before/after/delta, with evidence.
  Explanation calls the configured Agent/model client (mock offline).
- `personalize.py`: analyst metrics/tactical labels vs casual plain captions; viewer-scoped ★
  favourites/player_cam; en/es/fr offline phrase table and live LLM translation with fallback.
- `pitchsim/story.py`, `stories/*.yaml`, CLI `--story` plant deterministic labeled style changes.
- API `/gallery/sse` + `/gallery/ws`: event/cue/trace JSON, requested viewer/kill/rollout params,
  isolated temporary checkpoint directories, CORS localhost:5173; existing mounted stats MCP retained.
- API now depends on gallery-agents: CI and README install gallery-agents before replay-api.

Limits / next work:
- Azure/Foundry model calls, credentials, Cosmos state/checkpoints, deployment and tracing require
  Phase 4 and have not been exercised against Azure. All acceptance tests are offline.
- What-If is an approximate event-model continuation, not real-world calibrated probabilities.
  Snapshot styles now include recorded scripted style changes and observed red-card effects. `late_comeback.yaml` plants a labeled comeback attempt, not a guaranteed win.
- Phrase-table translations are intentionally small; live translation quality needs cloud evals.
- API session history is ephemeral; CLI checkpoints persist. No automatic multi-session resumption.
- No commits created: operator will commit (read-only .git).

Suggested conventional commit split once Git is writable:
1. `feat(stats): add deterministic stats engine and streamable MCP service`
2. `feat(agents): add typed Director workflow and offline demo`
3. `docs: document Phase 2A setup and handoff`

## Phase 1 foundation (historical baseline)
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

## Original Phase 2 attempt (historical salvage reference)
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

### Known issues in the salvage (fixed or deferred as noted above)
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
