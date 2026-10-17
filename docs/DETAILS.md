# Playmakers: technical details

Full reference moved from the README. See [README](../README.md) for the overview.

**Playmakers** is an AI production crew that turns a live football match event stream into explainable, timed overlay cues and personalized audience output.

This repository is being built for the **Microsoft x Premier League “Inside the Game” developer hackathon**. It uses **synthetic, football-realistic data only**, with **fictional clubs and players** (no Premier League marks).

## Phase 1 (foundation)

Phase 1 ships the foundation:

- **PitchSim**: a deterministic, seeded match-event simulator that produces a full 90-minute match as a timestamped event stream.
- **Shared contracts**: a typed, versioned event schema (JSON Schema + Pydantic).
- **Streaming replay**: a FastAPI service that replays a simulated match over **SSE** or **WebSocket**, in real-time or accelerated (e.g. 10×).
- **Azure template**: `azd` + Bicep for Foundry, Application Insights and Container Apps (see the README "Run on Azure" section; validated locally, not deployed).
- **CI**: lint + tests run on GitHub Actions.

## Phase 2A (implemented)

The Director is a real Microsoft Agent Framework `WorkflowBuilder` with parallel Tactics
and Storyline Agents, a synchronized Compliance join, Graphics and audience executors.
Every executor emits versioned `AgentTraceEvent` records. Typed shared state uses a
`MatchStore` Protocol and an in-memory implementation; Cosmos is planned for Phase 4.

Stats are code only: possession, pressure index, pass difficulty, xG, momentum and
control vs chaos (normalized pass-network entropy and failed-pass turnover rate).
All results cite event IDs. Compliance checks each insight against the Stats packet that the
deterministic engine computed from stored events up to that event, verifies metric evidence and numeric prose, and requests at most
two corrections per insight before emitting an evidence-backed template. Graphics
validates the cue schema, including timing, layer and broadcast safe area.

Run offline with no credentials:

```bash
python -m playmakers_agents demo --seed 7 --speed 50 --persona analyst
# Quick smoke check; --speed 0 runs without replay waits:
python -m playmakers_agents demo --seed 7 --speed 0 --limit 10
python -m stats_mcp
```

The demo prints JSON lines with `type: cue` or `type: trace`. It persists Agent Framework
superstep checkpoints in gitignored `data/checkpoints` (`--checkpoint-dir` overrides it).
The full 90-minute replay takes roughly two minutes at 50× plus workflow overhead.
Standalone MCP is at `http://127.0.0.1:8765/mcp`; the replay API also mounts it at
`http://127.0.0.1:8000/stats-mcp/` and manages its session-manager lifespan.

Default model access uses `DeterministicMockChatClient`, including actual Agent calls.
The mock does not request tools; the offline Stats executor invokes the same pure engine
functions exposed by MCP. When live models are configured, Stats calls MCP through
`MCPStreamableHTTPTool` and checks the results against local evidence. Tactics and
Storyline receive its read-only tools on shots and goals only. Inside the API, MCP is
mounted at `/stats-mcp/`, which is the live default (`http://127.0.0.1:8000/stats-mcp/`).

**Key-moment gate:** Tactics and Storyline call the model only for shots, goals, fouls,
cards, substitutions, kickoff and period events, and every 30th event (a tactical beat).
Other events get a rule-written insight from the verified metrics (for example "Pass
difficulty 0.08 / Northbridge Rovers pressure index 0.13."), which goes through the same
Compliance check and carries provenance `source: template, compliance: verified`; the
trace shows `templated`. Kill-recover replays only gated events. Measured with the mock
and two viewer profiles: 214 model calls for seed 7 and 185 for seed 42 (102 and 89
events per agent, 9 and 6 What-If explanations, one recap), down from 3,148 and 3,029.
`tests/test_model_gate.py` pins the seed-7 count.

Configuration (see [.env.example](../.env.example); export variables in your shell):

- Azure OpenAI: `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT`.
- Foundry: `AZURE_AI_PROJECT_ENDPOINT` + `AZURE_AI_MODEL_DEPLOYMENT`.
- `STATS_MCP_URL` selects another endpoint, such as the standalone server (`http://127.0.0.1:8765/mcp`).
- `AZURE_CLIENT_ID` selects a user-assigned managed identity.
- `PLAYMAKERS_AGENT_TIMEOUT_S`, `PLAYMAKERS_TRANSLATION_TIMEOUT_S`, `PLAYMAKERS_WHATIF_TIMEOUT_S` (live defaults 8, 3, 3 seconds).
- `APPLICATIONINSIGHTS_CONNECTION_STRING` turns on Azure Monitor tracing with Agent Framework instrumentation (`PLAYMAKERS_TRACE_CONTENT=0` leaves prompts and responses out).

Both live clients use `DefaultAzureCredential` (for example an existing Azure CLI login
locally, managed identity when deployed). Incomplete Azure OpenAI configuration uses
the mock; a Foundry endpoint without a model deployment raises a clear configuration
error. Cloud responses have not been exercised yet; offline tests require no Azure.

Regenerate overlay/trace JSON Schemas with `python -m playmakers_agents.export_schemas`.
Schemas are committed under `packages/playmakers_schema/src/playmakers_schema/schemas/v1/`.

## How the agents work (Phase 2B)

```mermaid
sequenceDiagram
    participant Replay as PitchSim Replay API
    participant Director
    participant Stats as Stats / MCP
    participant Writers as Tactics + Storyline
    participant Compliance
    participant Graphics
    participant Audience
    participant Checkpoint as Checkpoint storage
    Replay->>Director: Seeded MatchEvent
    Director->>Stats: Compute evidence-backed metrics
    Stats->>Writers: Parallel explanation requests
    Writers->>Compliance: Typed insights with evidence IDs
    Compliance->>Writers: Up to two corrections, within deadline
    Compliance->>Graphics: Verified insights or deterministic templates
    Graphics->>Audience: Schema-validated cues
    Audience-->>Replay: Analyst and casual cues in en es fr plus traces
    Director->>Checkpoint: Match history + per-agent sequence
    opt Tactics fails or exceeds its deadline
        Director->>Graphics: Template on the same event
        Director->>Checkpoint: Load last successful agent sequence
        Director->>Writers: Recreate Tactics and replay missed events
        Writers->>Compliance: Verify replay before resuming
    end
    opt Goal, big chance, or red card
        Director->>Director: What-If: parallel seeded PitchSim continuations
        Director->>Audience: Before, after and counterfactual probabilities
    end
```

**Kill and recover:** Tactics has a 4-second deadline offline (8 seconds with a live
model), shared across generation and correction attempts; Graphics has a 1.5-second deadline. Exceptions and timeouts open
a circuit breaker. A failed Tactics branch immediately supplies an evidence-backed
`template_fallback` cue; Storyline continues. The next event probes recovery. Repeated
failures back off for 1, 2, 4, 8, then 16 events. Traces expose `agent_down`, `fallback_on`,
`restarted_from_checkpoint`, and `caught_up`. Catch-up results pass Compliance and are
not rebroadcast as stale cues.

Framework `FileCheckpointStorage` saves both workflow supersteps and a versioned
match-history/agent-progress checkpoint on the first event, every 25 sequences, kill/recovery boundaries and full time. Agent progress stays current in memory between saves. After a crash, restore the last checkpoint and replay the unsaved tail. `RecoveryStorage` separates restoration from
its backend; a fresh Director can call `await director.restore(match_id)` before
consuming later events. Checkpoint folders are local development data, not a multi-user
service database. API sessions use isolated temporary folders cleaned on disconnect;
CLI checkpoints persist in `data/checkpoints`. Cosmos durability comes in Phase 4.

**What-If:** goals, non-goal shots with xG > 0.3, and red cards trigger 200 rollouts per
scenario by default. Three process workers compare the event prefix before, after, and
counterfactual at the same clock using common per-rollout seeds. Goal counterfactual:
“if the shot had been saved”; big chance: “if the chance had been scored”; red card:
“if the red card had not been shown”. `payload.metrics` includes `before`, `after`,
`counterfactual` win/draw/loss distributions, `win_prob_before`, `win_prob_after`, `delta`,
and `rollouts`. All probabilities refer to the **home team**. The explanation uses the
model-client interface, including the deterministic offline mock. A local first-goal
benchmark with 200 rollouts took **1.70s including worker startup**; hardware and live
model latency vary. These are approximate PitchSim continuations, not calibrated real
football forecasts; story-driven style changes beyond observed red cards are not yet
reconstructed in snapshots.

**Two audiences:** Analyst cues retain full verified metrics and tactical labels.
Casual cues use shorter emotional captions, fewer numbers, and ★ favourite-team/player
emphasis; `player_cam` appears only when that viewer's favourite is involved in the event.
English, Spanish and French work offline through a small phrase table. Configured live
models translate captions, with phrase-table fallback on timeout or invalid output.

Run the signature demo or a short recovery smoke check:

```bash
python -m playmakers_agents demo --seed 7 --speed 50 --persona analyst --kill tactics@20
python -m playmakers_agents demo --speed 0 --limit 5 --kill tactics@0 --whatif-rollouts 20
python -m playmakers_agents demo --speed 50 --persona casual --language es --favourite-player-id match_7_H09
python -m playmakers_agents demo --seed 7 --story stories/press_collapse.yaml --speed 50
python -m pitchsim simulate --seed 7 --story stories/late_comeback.yaml
```

`stories/*.yaml` applies deterministic style changes and plants persistent labels from
the scripted minute for later evaluation. `late_comeback` plants a comeback **attempt**,
not a guaranteed scoreline.

Start `uvicorn replay_api.main:app --port 8000`, then:

```bash
curl -N "http://localhost:8000/playmakers/sse?seed=7&speed=50&persona=casual&language=es&kill=tactics@20&whatif_rollouts=200"
websocat "ws://localhost:8000/playmakers/ws?seed=7&speed=50&persona=analyst&kill=tactics@20"
```

Both endpoints accept `seed`, `speed` (0 = no waits), `persona`, `language`,
`favourite_team_id`, `favourite_player_id`, `kill`, and `whatif_rollouts` (1–2000).
Messages are flat JSON objects with `type: "event" | "cue" | "trace"`; SSE uses ordinary
`data:` frames suitable for `EventSource.onmessage`. CORS defaults to `http://localhost:5173`; set `CORS_ORIGINS` to a comma-separated allowlist before starting the API.
The stats MCP service remains mounted at `/stats-mcp/`.

Cues may carry an optional `provenance` object (agent, source, Compliance verdict, attempts,
rejection reasons, metrics used and the events behind each metric). At the final whistle the
stream adds one `recap` cue per viewer profile (priority 90, 30 s, payload `headline`,
`detail`, `home_goals`, `away_goals` and `moments`). `GET /speech/config` reports whether
Azure AI Speech is configured; `GET /speech/synthesize?text=…&language=en|es|fr` (header
`X-Playmakers-Speech: 1`, at most 280 characters) returns MP3 audio, or 503 when Speech is
not configured.

Validation: 40 offline tests cover the workflow, recovery/replay, timeout/crash backoff,
What-If determinism, personalization, translation fallback, scripts and SSE/WS/MCP.
The full seed-7 kill demo emits 3,147 cues and 9,428 traces, with one fallback cue and
nine What-If cards. Ruff, calibration and dependency checks pass; a clean Python 3.13
virtual environment also installs and passes the suite.

## Pipeline fit (hackathon brief)

The hackathon asks for a single pipeline with five stages:

- **Ingest**: PitchSim events are replayed over SSE/WS.
- **Interpret**: Phase 1 emits calibrated match events + ground-truth labels (Phase 2 stats/tactics tools/agents build on this).
- **Explain**: Tactics and Storyline run as Agent Framework Agents, joined by Compliance.
- **Render**: Graphics validates OverlayCue JSON; the visual renderer comes in Phase 3.
- **Personalize**: audience fan-out shapes metrics, captions, favourites and language for each profile.

## Architecture

```mermaid
flowchart LR
  PitchSim --> Replay["Replay API SSE and WS"]
  PitchSim --> Director["Agent Framework Director"]
  Director --> Stats["Stats executor"]
  Stats --> Tools["StatsEngine and stats MCP"]
  Stats --> Tactics["Tactics Agent"]
  Stats --> Storyline["Storyline Agent"]
  Tactics --> Compliance
  Storyline --> Compliance
  Compliance --> Graphics["Validated OverlayCue"]
  Graphics --> Audience["Viewer fan-out"]
  Director --> Checkpoints["FileCheckpointStorage"]
  Tactics -. configured .-> Models["Azure OpenAI or Foundry"]
  Storyline -. configured .-> Models
```

## Repo layout

- `packages/playmakers_schema/`: versioned event contracts (JSON Schema + Pydantic models)
- `packages/pitchsim/`: simulator + validation CLI (`python -m pitchsim ...`)
- `services/replay_api/`: FastAPI SSE/WS replay endpoints
- `packages/playmakers_agents/`: Director workflow, typed handoffs, model clients, Compliance and CLI
- `packages/playmakers_stats/`: deterministic stats engine with evidence
- `services/stats_mcp/`: streamable HTTP stats tools, standalone or API-mounted
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
python -m pip install -e packages/playmakers_schema
python -m pip install -e packages/pitchsim
python -m pip install -e packages/playmakers_stats
python -m pip install -e services/stats_mcp
python -m pip install -e packages/playmakers_agents
python -m pip install -e services/replay_api
python -m pip check
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
uvicorn replay_api.main:app --reload --port 8000
```

In another shell, connect via SSE (example: 10× speed):

```bash
curl -N "http://127.0.0.1:8000/replay/sse?seed=123&speed=10"
```

### Live replay (WebSocket)

```bash
websocat "ws://127.0.0.1:8000/replay/ws?seed=123&speed=10"
```

## Notes

- **Synthetic-only**: no real match data, no Premier League marks.
- **Deterministic numbers**: downstream explanation agents must cite event IDs; no invented stats.


## Playmakers broadcast UI (Phase 3)

The React + Vite + TypeScript Playmakers app shows **Analyst** and **Fan** feeds side by side,
with a shared event clock, a Canvas pitch, timed evidence-backed overlays and a live agent trace.
All clubs and crest shapes are fictional. `/about` explains the architecture and current deployment status.

With the Python packages installed using the instructions above, run these in separate terminals:

```bash
# Repository root; offline mock models require no credentials
uvicorn replay_api.main:app --port 8000

# Frontend (Node 20.19+)
cd web
npm ci
npm run dev
```

Open **http://localhost:5173**. `VITE_API_BASE` defaults to `http://localhost:8000`;
set it in `web/.env.local` for another API origin. Set `CORS_ORIGINS` on the API to allow other web origins (default `http://localhost:5173`). The client uses one EventSource per audience, backed by one shared Director and 200-rollout What-If session, and retries
with bounded backoff and deduplicates the deterministic replay after reconnection.
The slower stream determines the shared event clock.

- Choose seed and speed (1×, 10×, 50×); changing either restarts both feeds.
- Fan controls select Spanish/French and a fictional roster number. Changing the fan
  profile replays that feed until it synchronises with the analyst.
- Pause freezes the displayed program; network feeds continue buffering. Start returns to live.
- Toggle safe-area guides. Cue timing uses the match clock, duration, priority and one winner per slot.
- **Stop Tactics agent** restarts both deterministic sessions with failure at the current minute.
  The API fast-forwards the prefix (`replay_from_ms`) before returning to the selected pace.
  Look for `agent down → fallback on → restarted from checkpoint → caught up` in both feeds.
  One injected failure per replay; changing seed/speed resets the button.
- Score/clock, storyline/tactical lower thirds, momentum, pass difficulty, xG shots,
  favourite tags and What-If probability cards respond to actual events/cues.

![Playmakers split view connected to the local API](../web/e2e-screenshot.png)

Screenshot/GIF placeholder for the submission: replace or supplement this capture with
`docs/media/hero.png` and a short kill/recover recording once the final theme is locked.

```bash
cd web
npm run types:generate   # json-schema-to-typescript; output in src/generated is versioned
npm run lint
npm test
npm run build
npx playwright install chromium
npm run screenshot      # API :8000 + Vite :5173 must already be running
```

The Chromium script captures `web/e2e-screenshot.png` at 1920×1080 and checks live persona
content, the shared clock, pause/start, kill/recover traces and `/about`. It also saves
1440×900 captures to `web/shots/main.png` (mid-match insights), `kill.png` (recovery)
and `about.png`, and asserts no horizontal overflow at both viewport sizes.
The Calm light theme uses locally bundled Inter (SIL OFL), a single `web/src/tokens.css`
for design tokens, a shared scoreboard, two audience cards, an Agents list with expandable
handoff history, and an event-driven match timeline. On restricted
machines use `PLAYWRIGHT_BROWSERS_PATH=/tmp/playmakers-playwright` for both installation and execution.
Set `PLAYMAKERS_WEB_URL` to override the screenshot target URL (default `http://localhost:5173`).
CI runs npm ci, contract drift detection, lint, unit tests and production build on Node 20.

Current visual limits: PitchSim emits ball/action positions but no full player tracking frames
in its default replay. The 22 dots therefore use formation-based motion around the observed ball;
tracking frames are supported when present. Pause/resume is a local program freeze, not server pause.
Reconnect rebuilds ephemeral server sessions rather than resuming a stored session. Offline fan
translations use the small phrase table. What-If probabilities remain synthetic approximations.
Azure deployment, Cosmos persistence and cloud observability are Phase 4 work.

What-If snapshots now replay scripted style-change metadata from events (including YAML stories),
as well as red cards. A supplied story schedule supports older recordings and future rollout changes;
recorded changes take precedence so they are not applied twice.

### Calm replay controls

Choose a seed, speed, language and fictional favourite player in the header; press **D** to
show broadcast safe areas. The For you card retains the latest What-If result until a newer
simulation arrives. Pitch player motion is a seeded formation visualisation. Analyst possession
is team-tagged event share, PPDA is opposition passes per home defensive action, and field tilt
is home share of final-third pass entries; these are synthetic event proxies.

With API on :8000 and Vite on :5173, `cd web && npm run screenshot` captures the playing replay,
Tactics recovery and About in `web/shots/`, and checks both 1440×900 and 1920×1080 for clipping.


Shared SSE sessions use `(seed, speed, kill, whatif_rollouts, replay_from_ms)` plus
an explicit viewer configuration. Both web requests send the same `viewer_profiles`
JSON array (Pydantic `ViewerProfile` fields, including `favorite_player_id`), and
select their own `persona`/`language`. Different viewer configurations are isolated.
Without the array, the API includes all six persona/language combinations; requests
with the same configuration share a producer. Cues are filtered per subscriber;
events and lifecycle traces are broadcast to both. Late subscribers read the
session's history from kickoff. Disconnecting one viewer leaves the other running;
the last disconnect cancels the producer and closes its Director. Sessions are
in-memory and scoped to one API process; use one worker for this demo. No durable
resume or cross-process session coordination is claimed.

React flushes incoming messages every 75 ms, retaining the last 2,500 events,
2,400 traces, and active cues plus the latest 400 cues. Pausing freezes the displayed
sequence while streams continue; a pause longer than the retained window can lose
old presentation history. Ordinary reconnects replay retained backend history while
another subscriber keeps the session alive; otherwise they rebuild the seeded match.

Run the container demo from the repository root with `docker compose up --build`,
then open **http://localhost:5173**. The API listens on :8000; Stats MCP is mounted
at `/stats-mcp/`, so no separate MCP container is needed. The web image builds with
Node and serves with nginx, including an unbuffered same-origin `/api` proxy to
`API_UPSTREAM` (default `http://api:8000`). Set `API_UPSTREAM=` (empty) to drop the proxy,
for example in Container Apps where no `api` host exists, and point `API_BASE` at the API's
public URL instead (with that web origin in the API's `CORS_ORIGINS`).
`API_BASE` writes `/config.js` at container startup (default `/api`), so the built
image can use another API URL without rebuilding. Use an API URL/path containing
only letters, digits, `:`, `/`, `.`, `_`, or `-`. The API image runs as an unprivileged
user. Local file checkpoints are temporary, so the API must run as a single replica.

CI now installs Chromium and runs `npm run screenshot` against the real local API
and Vite. Failures fail the job; screenshots and API/web logs are uploaded as artifacts.
