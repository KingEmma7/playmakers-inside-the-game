# PLAN — Playmakers build, 14 → 26 Oct 2026 (solo, Codex)

> Historical build plan. Phase prompts below are kept as written; `salvage/` no longer exists.
>
> **What was actually built differs from this plan.** Not built: Cosmos DB (state is in memory,
> checkpoints are files), Event Hubs, Container Registry, the Azure MCP Server (only the custom Stats MCP
> server exists), the `evals/` package and the Foundry evaluation gate in CI, docs/DEPLOY.md, docs/PITCH.md
> and the `?demo=1` mode. GitHub Copilot was not used; the code was written with AI coding assistants (Codex
> and Cursor) under King Emmanuel's direction. Built but not yet run against Azure: the Foundry and Azure
> OpenAI model clients, Application Insights tracing, the Azure AI Speech voice and the `infra/` azd + Bicep
> template (validated locally, never deployed). The README is the source of truth for what runs today.

Hard deadline: **27 Oct 11:59pm PT = Wed 28 Oct 06:59 GMT**. Target submit: **Mon 26 Oct evening GMT**.
Tue 27 Oct is buffer only. Times below are GMT (Accra).

**How to use this file:** each phase has goals, acceptance criteria, and a **ready-to-paste Codex prompt**.
Paste one prompt per Codex task. If a phase is big, Codex may stop part-way — reply
"Continue with the remaining items in the phase prompt; re-run the definition of done." Don't start the next
phase until the current one's acceptance criteria pass.

| Day | Date | Work | Phase |
|---|---|---|---|
| 1 | Wed 14 Oct | Push repo to GitHub, connect Codex, start Phase 2A | 2 |
| 2 | Thu 15 Oct | Phase 2A finish (stats + MCP + contracts + workflow skeleton) | 2 |
| 3 | Fri 16 Oct | Phase 2B (kill/recover, checkpoint, What-If, personalization, /playmakers stream) | 2 |
| 4 | Sat 17 Oct | Phase 2B finish + bug fixes; **sign up for Azure free account** | 2 |
| 5 | Sun 18 Oct | Phase 3 (React overlay UI, pitch canvas, analyst vs fan side by side) | 3 |
| 6 | Mon 19 Oct | Phase 3 finish (agent trace panel, kill button, What-If card) | 3 |
| 7 | Tue 20 Oct | Phase 4A (Foundry model client live, Cosmos store, Dockerfiles) | 4 |
| 8 | Wed 21 Oct | Phase 4B (azd up to Container Apps; public demo URL works) | 4 |
| 9 | Thu 22 Oct | Phase 4C (evals: planted-moment recall/precision + groundedness; CI gate; tracing) | 4 |
| 10 | Fri 23 Oct | Phase 5A (README, diagrams, eval report, polish UI) | 5 |
| 11 | Sat 24 Oct | Rehearse demo; record video takes | 5 |
| 12 | Sun 25 Oct | Edit video (<2:00), upload to YouTube, final README links | 5 |
| 13 | Mon 26 Oct | **Submit**: checklist below; then freeze `main` | 5 |
| — | Tue 27 Oct | Buffer only (fix anything a judge link breaks) | — |

**Fallback rule (protect the submission):** if by Wed 21 Oct Azure isn't working, deploy the offline-mock
version (it still runs the full multi-agent pipeline) to any free host and keep Azure as "deploy with azd"
instructions + IaC. A working demo beats a half-deployed one.

---

## Phase 2 — Agent pipeline (14–17 Oct)

### Goals
Real Microsoft Agent Framework workflow with 7 agents + personalizer, deterministic stats behind an MCP
server, typed handoffs, checkpointing, kill-and-recover with template fallback, What-If rollouts,
personalization, overlay cues streamed from the API. Offline mock model client so all of it runs without Azure.

### Acceptance criteria
- `pip check` clean; `ruff format --check . && ruff check . && pytest` green offline; CI updated.
- `python -m playmakers_agents demo --seed 7 --speed 50 --persona analyst` prints overlay cues to the terminal.
- `... --kill tactics@20` (kill Tactics at minute 20) shows: fallback template cues within 1 event,
  "restarted from checkpoint", catch-up, then normal cues. Test covers this.
- What-If cue at the first goal with `win_prob_before/after/delta`, N rollouts (default 200, parallel), evidence ids.
- Analyst vs casual(es, favourite player) feeds differ in content (not only translation). Test asserts this.
- `stats_mcp` runs standalone (`python -m stats_mcp`) and LLM agents call its tools through Agent Framework's
  MCP tool (`MCPStreamableHTTPTool`) when an LLM client is configured; offline path calls the same functions directly.
- `/playmakers/sse` and `/playmakers/ws` stream personalised `OverlayCue` JSON + agent trace events.
- Every cue has `evidence_event_ids`; Compliance rejects otherwise (with up to 2 retries then template).

### Codex prompt — Phase 2A (paste first)
```text
You are continuing the "Playmakers" project in this repo. First read AGENTS.md, docs/HANDOFF.md and docs/PLAN.md
completely, then run the commands in AGENTS.md §5 to confirm Phase 1 is green before changing anything.

Task: Phase 2A — stats engine, MCP server, contracts, and the Agent Framework workflow skeleton.
Use salvage/phase2/ as a head start (it is recovered, untested code from a crashed run — copy and fix, never
import from salvage/). Respect AGENTS.md §7 dependency pitfalls (no openai<2 pin; agent-framework-core;
mcp>=1.24,<2; run pip check).

1. Create packages/playmakers_stats (port salvage version): deterministic StatsEngine with possession,
   pressure_index, pass_difficulty, xg, momentum, plus control_vs_chaos (pass-network entropy + turnover rate).
   Every result is a Pydantic model including Evidence(event_ids). Unit tests with hand-built event lists.
2. Create services/stats_mcp (port salvage): FastMCP server exposing ingest_event + the stats tools, runnable via
   `python -m stats_mcp` (streamable HTTP, port 8765) and mountable into replay_api at /stats-mcp. Add a test that
   starts it in-process and calls a tool via the mcp client (streamable_http_client).
3. In packages/playmakers_agents: port contracts.py (ViewerProfile, Insight, OverlayCue with layer, template,
   clock_ms, duration_ms, priority, safe_area, evidence_event_ids, persona, language; ComplianceDecision; plus
   AgentTraceEvent{agent, action, latency_ms, status}). Export JSON Schemas for OverlayCue/AgentTraceEvent into
   packages/playmakers_schema/.../schemas/v1/. Replace the Phase 1 dataclasses in interfaces.py with these.
4. Port model_clients.py: DeterministicMockChatClient (default), Azure OpenAI / Foundry clients selected only when
   env vars are set (AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT, or AZURE_AI_PROJECT_ENDPOINT). Inspect the
   installed agent_framework package to use its real APIs (Agent, BaseChatClient, WorkflowBuilder, executors,
   CheckpointStorage/FileCheckpointStorage, MCPStreamableHTTPTool) — do not guess signatures; read the source in
   site-packages.
5. Build the Director as an Agent Framework workflow (WorkflowBuilder) with executors: Stats (tools only, no free
   text) → Tactics + Storyline (LLM via client; must cite event_ids) → Compliance (code check of every number
   against StatsEngine by event_id; reject → retry ≤2 → template) → Graphics (schema-validated OverlayCue) →
   Audience fan-out. Each executor emits AgentTraceEvent. Shared InMemoryMatchStore with a MatchStore Protocol
   (Cosmos implementation comes in Phase 4).
6. CLI: `python -m playmakers_agents demo --seed 7 --speed 50 --persona analyst` prints cues + trace lines.
7. Update CI (install new packages), README (Phase 2 section). Fix the known salvage issues listed in HANDOFF.md.
Definition of done = AGENTS.md §8. Commit in small conventional commits. Finish with a summary: what was built,
how to run, test count, and anything left for Phase 2B.
```

### Codex prompt — Phase 2B
```text
Read AGENTS.md, docs/HANDOFF.md, docs/PLAN.md. Confirm Phase 2A acceptance passes first (ruff, pytest, demo CLI).

Task: Phase 2B — resilience, What-If, personalization, streaming.
1. Checkpointing & recovery: use Agent Framework checkpoint storage (FileCheckpointStorage now, behind an interface
   so Cosmos can be added). Per-agent timeouts (latency budget: graphics 1.5s, tactics 4s), circuit breaker, and
   deterministic template fallback captions. CLI flag `--kill tactics@20` (agent@match-minute) and API query param
   `kill=tactics@20`: the agent crashes; Director re-routes; Graphics emits template cues within one event; agent
   restarts from last checkpoint and replays missed events to catch up; trace shows each step
   (agent_down, fallback_on, restarted_from_checkpoint, caught_up). Tests for all of this.
2. What-If agent: port salvage pitchsim/whatif.py (MatchSnapshot, snapshot_from_events, rollout_from_snapshot).
   Trigger at goals, big chances (xG>0.3), red cards. Run N rollouts (default 200) in a ProcessPoolExecutor with
   per-rollout seeds; compute win/draw/loss probabilities before vs after vs counterfactual ("if the shot had been
   saved"); emit a What-If OverlayCue with metrics + 1–2 sentence explanation (LLM via client, mock offline).
   Deterministic given the seed. Keep it under 2s at N=200 on a laptop; test with N=20.
3. Personalization (Audience agent): profiles Analyst (dense metrics, xG, pressure index, tactical labels), Casual
   (plain language, fewer numbers, emotion, favourite club/player emphasis with ★ and player-cam cues), language
   (en/es/fr via LLM with a small offline phrase table fallback). Test that analyst and casual feeds for the same
   event differ in fields and wording, and that favourite-player cues appear only for that profile.
4. Story scripts: port pitchsim/story.py; add `stories/*.yaml` (e.g. "press collapse after 60'", "late comeback")
   with planted ground-truth moments used later by evals.
5. replay_api: add /playmakers/sse and /playmakers/ws (params: seed, speed, persona, language, favourite_team_id,
   favourite_player_id, kill, whatif_rollouts) streaming {type: "event"|"cue"|"trace", ...} messages; mount stats MCP
   at /stats-mcp; CORS for localhost:5173. Tests with httpx/TestClient.
6. README: "How the agents work" section with a mermaid sequence diagram, kill/recover explanation, how to run demo.
Definition of done = AGENTS.md §8. Small commits. Summarise results and list anything needing Azure.
```

---

## Phase 3 — Frontend overlay UI (18–19 Oct)

### Goals
A broadcast-style web app (React + Vite + TypeScript) that plays the synthetic match on a 2D pitch canvas
with overlays popping in sync, an agent trace ("Playmakers crew") panel, and **Analyst vs Fan side by side**.

### Acceptance criteria
- `cd web && npm ci && npm run dev` works against local API; `npm run build`, `npm run lint`, `npm test` pass; added to CI.
- Split view: left = Analyst feed, right = Casual/Spanish/favourite-player feed, same match clock.
- Overlays: score bug, lower third, momentum bar, pass-difficulty arc, xG shot card, What-If card; respect safe area.
- Agent trace panel lists handoffs with latency and status; "Kill Tactics" button triggers kill/recover visibly.
- Controls: seed picker, speed (1×/10×/50×), persona/language/favourite selectors. Fictional team crests generated (SVG shapes).
- Looks polished at 1920×1080 (for recording). No PL branding.

### Codex prompt — Phase 3
```text
Read AGENTS.md, docs/HANDOFF.md, docs/PLAN.md. Confirm backend tests pass and /playmakers/sse streams locally.

Task: Phase 3 — build web/ (React + Vite + TypeScript) broadcast overlay UI.
1. Scaffold web/ with Vite React-TS, ESLint, Vitest + Testing Library. TypeScript types for MatchEvent,
   OverlayCue, AgentTraceEvent mirrored from the JSON Schemas in packages/playmakers_schema (generate with
   json-schema-to-typescript via an npm script, commit the output).
2. Data layer: hook usePlaymakersStream(params) connecting to /playmakers/sse (EventSource) with reconnect; one stream per
   view. API base URL from VITE_API_BASE (default http://localhost:8000).
3. Pitch: Canvas 2D top-down pitch, ball + 22 player dots moving from event positions (interpolate between events),
   fictional team colours/crests (generated SVG shapes; no real badges).
4. Overlay layer (absolutely positioned over the pitch, 16:9, broadcast safe-area guides toggle): score bug + clock,
   lower third (storyline), momentum bar, pass-difficulty arc, xG shot card, What-If card (win% before/after,
   delta bar, explanation), ★ favourite-player tag. Cues appear/disappear by clock_ms + duration_ms with
   tasteful CSS animations; priority decides stacking.
5. Layout "Playmakers": header with controls (seed, speed 1/10/50x, start/pause), two synced panels side by side —
   ANALYST and FAN (persona casual, language es/fr, favourite player picker). Right rail: Agent Trace panel showing
   each agent's handoffs, latency, status colours; status chips per agent (up/down/fallback/recovering).
   A red "Kill Tactics agent" button that restarts the stream with kill at current minute (or calls an API endpoint
   if available) so recovery is visible in both panels and the trace.
6. Make it look premium at 1920x1080: dark broadcast theme, good typography (system/Inter), no sports-brand
   lookalikes. Add a /about page summarising architecture for judges.
7. Tests: cue timing logic, persona panels render different content, trace panel updates. Add web job to CI
   (node 20: npm ci, lint, test, build). Update README with screenshots placeholder + run instructions.
Definition of done = AGENTS.md §8 (+ web lint/test/build). Small commits. Summarise and list rough edges.
```

---

## Phase 4 — Azure (20–22 Oct)

### Goals
*(Planned. Cosmos DB, Event Hubs and the eval gate were not built; see the note at the top.)*
Real models via **Microsoft Foundry**, state + checkpoints in **Cosmos DB**, services on **Azure Container
Apps** via `azd up`, observability (App Insights/Foundry tracing), and a **Foundry evaluation gate in CI**.
Public demo URL for judges.

### Acceptance criteria
- `azd up` from a clean clone provisions: Container Apps env, apps `api` (replay_api + agents + /stats-mcp),
  `web` (static build via nginx or Static Web Apps), Cosmos DB (serverless), Log Analytics + App Insights,
  managed identity with RBAC to Cosmos + Foundry. No keys in code.
- With env set, agents use the Foundry model deployment; without, mock. Same tests pass offline.
- `evals/` computes insight recall/precision against planted story moments + groundedness (numbers match
  StatsEngine); `python -m evals run` produces `evals/report.md`; CI job fails if recall < threshold
  (offline mock eval always runs; Foundry-backed eval runs when secrets exist).
- Public URL loads the web app and streams a live match. README documents URL + `azd up`.
- Event Hubs optional — keep the Bicep but disable by default to save credits.

### Codex prompt — Phase 4A + 4B (deploy)
```text
Read AGENTS.md, docs/HANDOFF.md, docs/PLAN.md. Confirm everything is green locally.

Task: Phase 4 — make Playmakers cloud-native on Azure (I will run the azd commands myself; you write the code/IaC).
1. Model client: finalize Foundry support using the current Azure AI Projects / Agent Framework Foundry client
   (check installed package source for exact APIs). Config from env: AZURE_AI_PROJECT_ENDPOINT,
   AZURE_AI_MODEL_DEPLOYMENT (and Azure OpenAI fallback). Auth with DefaultAzureCredential. Use a small, cheap model
   for Director/Compliance and a stronger one for Tactics/Storyline (both configurable). Cache identical prompts;
   cap tokens; keep the mock as default.
2. CosmosMatchStore + CosmosCheckpointStorage implementing the existing interfaces (azure-cosmos async SDK,
   partition key /match_id). Selected when COSMOS_ENDPOINT is set. Tests use the in-memory/file versions; add an
   optional integration test skipped without env.
3. Dockerfiles: services/replay_api (includes agents + stats MCP mount), web (multi-stage: build → nginx, runtime
   API URL via env-substituted config.js). .dockerignore files. `docker compose up` runs both locally.
4. infra/: replace stubs with working Bicep for azd: Log Analytics, App Insights, Container Apps environment,
   Container Registry, user-assigned managed identity, Cosmos DB serverless (db "playmakers", containers state,
   checkpoints), container apps api (ingress external, port 8000, min replicas 1 for the demo) and web; role
   assignments (Cosmos data contributor, Cognitive Services OpenAI User / Azure AI User on the Foundry project);
   outputs for URLs. Parameterize the Foundry project endpoint (existing resource) rather than creating it.
   azure.yaml with services api + web. Event Hubs module present but disabled by default (param enableEventHubs=false).
5. Observability: OpenTelemetry → App Insights (azure-monitor-opentelemetry), Agent Framework tracing on;
   each AgentTraceEvent also emitted as a span.
6. Docs: docs/DEPLOY.md with exact steps for a beginner: az login, azd auth login, azd env new, azd env set
   AZURE_AI_PROJECT_ENDPOINT=..., azd up, how to find the URL, how to tear down (azd down) to save credits,
   and expected monthly cost with min replicas.
Definition of done = AGENTS.md §8; `az bicep build` on infra/main.bicep succeeds (install bicep in the sandbox if
possible). Summarise and give me the exact commands to run.
```

### Codex prompt — Phase 4C (evals + CI gate)
```text
Read AGENTS.md, docs/PLAN.md. Task: Phase 4C — evaluations as a quality gate (MatchDesk-style).
1. evals/ package: datasets generated from PitchSim story scripts with planted ground-truth moments
   (press collapse, momentum swing, late comeback, red card impact) over 20 seeded matches.
2. Metrics: (a) insight recall/precision — did Tactics/Storyline flag each planted moment within 90s of match
   time, (b) groundedness — every number in every cue matches StatsEngine for its evidence_event_ids,
   (c) latency p50/p95 per agent, (d) fallback rate. Write evals/report.md + evals/report.json.
3. When AZURE_AI_PROJECT_ENDPOINT is set, also run Azure AI Foundry evaluators (azure-ai-evaluation:
   GroundednessEvaluator/RelevanceEvaluator or current equivalents — check installed source) on a sample of cues and
   log results to the Foundry project.
4. CI: job "evals" runs offline evals on every PR and fails if recall < 0.8, precision < 0.7, or groundedness < 1.0;
   a second job runs Foundry evals only when repository secrets exist (OIDC via azure/login). Add a "prompt
   regression" test: a deliberately bad prompt fixture must fail the gate (prove the gate works).
5. README: "Quality gate" section with the latest report table.
Definition of done = AGENTS.md §8. Summarise numbers.
```

---

## Phase 5 — Polish & submission (23–26 Oct)

### Goals
Excellent README, demo video < 2:00, elevator pitch, submission done Mon 26 Oct.

### Acceptance criteria
- README top: one-line pitch, GIF/screenshot, demo URL, video link, architecture diagram (mermaid), hero tech
  table (where each Microsoft tech is used, with file links), how to run locally (offline, 3 commands), how to
  deploy (azd), synthetic data section (calibration table + season dataset + planted moments), evals table,
  judging-criteria map, limitations/next steps, MIT license.
- Video < 2:00, 1080p, no copyrighted music, captions, uploaded public/unlisted-public on YouTube.
- Repo public; no secrets (run `gitleaks` or `git log -p | grep -i key` check); fictional data only.

### Codex prompt — Phase 5
```text
Read AGENTS.md, docs/PLAN.md. Task: Phase 5 — polish for judges (judges may score from README + video only).
1. Rewrite README.md for judges: title + one-line pitch; badges (CI); hero screenshot placeholder
   (docs/media/hero.png) and demo GIF placeholder; "Try it" (live URL placeholder + local offline quickstart in
   ≤3 commands); "Why it matters" (broadcast graphics workflow, personalised second screen); architecture mermaid
   diagram + agent sequence diagram; table mapping each Microsoft technology actually used (Foundry, Agent
   Framework, MCP, Container Apps, Application Insights) to the files that use it; synthetic data section (PitchSim design,
   calibration table from `pitchsim validate --matches 50`, season dataset, planted moments); quality gate/eval
   table; resilience (kill/recover); judging-criteria map (one row per criterion with evidence links);
   limitations + roadmap; license. Keep it scannable.
2. docs/VIDEO.md: final 1:55 script + shot list (use the draft in docs/PLAN.md Phase 5 and tighten).
3. docs/PITCH.md: elevator pitch (≤100 words) + 300-word description for the submission form.
4. UI polish pass: loading states, error toasts, empty states, keyboard shortcut K = kill tactics, W = force
   what-if, D = toggle safe area; a "demo mode" URL (?demo=1) that auto-plays seed 7 at 10x and triggers kill at
   minute 20 and what-if at the first goal, for reliable recording.
5. Repo hygiene: scan for secrets, remove salvage/ folder once everything is ported (mention in commit), ensure
   .env.example, CONTRIBUTING.md short, issue templates optional. All checks green.
Summarise and list anything I must do by hand (recording, uploading, submitting).
```

### Demo video script draft (target 1:55)
| Time | Shot | Voice-over (write-out, read calmly) |
|---|---|---|
| 0:00–0:10 | Title card "Playmakers" over live split screen | "This is Playmakers: an AI production crew that turns a live match into broadcast graphics, and a different second screen for every fan." |
| 0:10–0:25 | Architecture diagram (README) | "A Microsoft Agent Framework workflow: two model-backed writers, Tactics and Storyline, plus deterministic Stats, Compliance, Graphics and Audience steps, a stats MCP server and file checkpoints." |
| 0:25–0:40 | PitchSim calibration report + season file | "There's no real data, so I built PitchSim: a calibrated, seeded simulator — a thousand passes, twenty shots, realistic goals — plus a 380-match season and planted moments for evaluation." |
| 0:40–1:00 | Live split screen, overlays popping; trace panel | "The Director routes each event: Stats computes numbers through MCP, Tactics and Storyline explain why it matters, Compliance checks every number against the data, Graphics puts it on air." |
| 1:00–1:20 | Click "Kill Tactics" — fallback, restart, catch-up | "Now I kill the Tactics agent mid-match. Graphics fall back to safe templates within one event… it restarts from its checkpoint and catches up. The broadcast never breaks." |
| 1:20–1:35 | Goal → What-If card | "At the goal, the What-If agent replays 200 alternate futures: if that shot had been saved, the home side's win chance drops from 61 to 38 percent." |
| 1:35–1:48 | Analyst vs Fan panels on the same moment | "Same moment, two audiences: dense tactics for the analyst, a simple Spanish card starring her favourite player for the fan." |
| 1:48–1:55 | CI + URL + GitHub | "Every change runs the tests and a browser journey in CI. Try it — link and code below." |
Record with OBS (free) at 1920×1080 using `?demo=1`; record voice separately; no music or royalty-free only.

### Elevator pitch draft
> Superseded. The original draft named Cosmos DB, seven specialised agents and a Foundry evaluation gate,
> none of which exist. The current pitch is kept outside the repo with the submission text.

### Submission checklist (Mon 26 Oct)
- [ ] GitHub repo **public**, README final, CI green on `main`, MIT LICENSE present.
- [ ] Live demo URL works in an incognito window (and on phone); if it sleeps, min replicas = 1 until judging ends (10 Nov).
- [ ] Video < 2:00, public on YouTube/Vimeo, link in README; shows the real app running; no copyrighted music; no PL marks.
- [ ] Elevator pitch + description pasted from docs/PITCH.md; technologies listed.
- [ ] Testing instructions (URL, demo mode `?demo=1`, how to kill an agent; credentials if any).
- [ ] All text in English. No secrets in git history. Only fictional clubs/players.
- [ ] Submit on the hackathon "Projects" page before **28 Oct 06:59 GMT** — aim for Mon 26 Oct evening. Screenshot the confirmation.
- [ ] Keep Azure running through judging (27 Oct – 10 Nov); set a budget alert.
