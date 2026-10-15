# Playmakers code review — pre-Azure (15 Oct 2026)

Scope: `/workspace/gallery-export` after Calm UI + Playmakers rename. Method: read key modules (replay API, Director workflow, What-If, personalize, resilience, stats engine, web stream/App), full pytest (47), live Playwright previously green, targeted repros.

Severity: **blocker** (breaks demo/judges or security) · **high** · **medium** · **low** · **nicety**.

---

## Summary counts

| Severity | Count |
|----------|------:|
| Blocker  | 1 |
| High     | 8 |
| Medium   | 11 |
| Low      | 7 |
| Nicety   | 5 |

Top 5 (fix these before Azure):
1. **[B1]** Dual SSE streams each run a full Director + What-If → 2× CPU/RAM and ~6000 cues for one UI page.
2. **[H1]** Unbounded `seed`/`speed` query params enable easy DoS (negative speed, speed=1e9).
3. **[H2]** What-If `evidence_event_ids` dumps **every** match event ID into each cue (1000+ IDs).
4. **[H3]** Compliance rebuilds a full `StatsEngine` from all events on every insight → O(n²) per match.
5. **[H4]** Shared What-If `ProcessPoolExecutor` can enter `BrokenProcessPool` with no recovery; API What-If stays dead until process restart.

---

## 1. Correctness & bugs

### B1 — Dual independent Directors for Analyst + Fan  · **blocker (demo scale)**
`web/src/App.tsx:104-120` opens two `usePlaymakersStream` hooks. Each hits `/playmakers/sse` and constructs its own `Director` (`services/replay_api/src/replay_api/main.py:100-106`) with `whatif_rollouts=200`. Same match is simulated and analysed twice; What-If runs twice.

**Impact:** At default demo settings the UI is the heaviest client. Judges' laptops / Azure free tier will struggle. Codex previously reported ~3,147 cues × 2 ≈ 6k cue messages plus ~9k traces × 2.

**Mitigation applied:** web uses `whatif_rollouts=40`. **Proper fix still open:** Single shared backend session (match_id + seed) with fan-out of personas inside one Director (`profiles=[analyst, casual]`), or a `/playmakers/sse` multiplex that already supports multiple profiles—wire the UI to one stream and filter by `persona`. Short-term: default `whatif_rollouts=20` for the web and raise only for the CLI kill demo.

### H1 — Unbounded seed/speed  · **high**
`main.py:131-132` (`seed: int = 7`, `speed: float = 50`) have **no** `Query(ge=…, le=…)`. `whatif_rollouts` and `replay_from_ms` are bounded. Negative or huge `speed` is accepted; `speed=0` is intentionally instant (tests rely on it) but still unbounded concurrency of such requests is a DoS.

**Fix:** `seed: Annotated[int, Query(ge=0, le=10_000)]`, `speed: Annotated[float, Query(ge=0, le=100)]` (keep 0 for tests). Same on WS.

### H2 — What-If evidence lists the entire match  · **high**
`what_if.py:178`: `evidence_event_ids=[row.event_id for row in events]`. Late-match What-If cues carry 1000+ IDs; JSON payload balloons; frontend stores them all.

**Fix:** Cite triggering event (+ optional short window / metric evidence). Keep last id = trigger (tests assert this).

### H3 — Compliance O(n²)  · **high** *(fixed)*
Was rebuilding a full `StatsEngine` from all events on every insight validation.

**Fix applied:** Validate insights against the `StatsPacket` already produced by StatsExecutor (same deterministic numbers, O(1)). Do **not** use the live engine here — it already contains the in-flight event and breaks kill-recover replay compliance. Added regression test.

### H4 — BrokenProcessPool not recovered  · **high**
`what_if.py:122-128` submits to a shared pool. If a worker dies (OOM, forced kill), `asyncio.gather` raises `BrokenProcessPool`. Lifespan pool is never replaced (`main.py:32-39`). Reproduced when running ad-hoc scripts; production risk under memory pressure.

**Fix:** Catch `BrokenProcessPool`, shut down, `create_rollout_pool()`, retry once; if using app.state pool, replace `app.state.whatif_pool`. Add test.

### H5 — SSE disconnect does not cancel mid-What-If promptly  · **high**
`main.py:151-165` uses `aclosing` (good) but never `await request.is_disconnected()`. A client close during a 200-rollout What-If waits for pool futures. Frontend reconnect storms amplify this (see M3).

**Fix:** Between events (and before What-If), if `await request.is_disconnected(): break`. Cancel pending What-If futures on Director exit (already partially done in `WhatIfAgent.close`).

### H6 — `app.state.whatif_pool` AttributeError without lifespan  · **high**
Bare `TestClient(app)` (no context manager) → `AttributeError: 'State' object has no attribute 'whatif_pool'` (`main.py:161`). Reproduced.

**Fix:** `getattr(request.app.state, "whatif_pool", None)` and document that clients must use lifespan; or initialise `whatif_pool = None` at import.

### H7 — WebSocket `/replay/ws` ignores disconnect  · **high**
`main.py:77-87` only special-cases `CancelledError`, always `ws.close()` in `finally`. Client disconnect during send can error noisily. `/playmakers/ws` handles `WebSocketDisconnect` correctly.

**Fix:** Mirror playmakers_ws handling.

### H8 — Recovery checkpoint writes full event list every event  · **high (perf/correctness under load)**
`workflow.py:644-656` serialises **all** events to `FileCheckpointStorage` after every event. I/O and disk grow with match length; concurrent SSE sessions write separately.

**Fix:** Incremental append, or checkpoint every N events / on kill only; keep last sequences in memory.

### M1 — Kill only supports `tactics`  · **medium**
`resilience.py:16-17`. Fine for demo; document. UI hard-codes "Stop Tactics agent".

### M2 — Numeric prose check is brittle  · **medium**
`workflow.py:313-319`: any number in headline/detail must equal a rounded metric. Clock times, jersey numbers, "2nd half" fail compliance → template spam for real Azure models.

**Fix:** Whitelist structural numbers or strip clock/jersey patterns before the check.

### M3 — Frontend reconnect replays full match  · **medium**
`stream.ts:88-98`: on error, reconnect with same query; dedupe by sequence. Backend still re-simulates and re-runs Director from kickoff (unless `replay_from_ms` set). Kill button sets `replay_from_ms` (`App.tsx`), good; network blips do not.

### M4 — `★` favourite marker  · **medium (brand)**
`personalize.py:110,128` prefixes `★`. Conflicts with Calm "no emoji/decorative marks" preference. Use text "Favourite ·" or a quiet SVG.

### M5 — Personalization overwrites analyst non-English content with generic blurbs  · **medium**
`personalize.py:64-71`: offline non-English analyst gets fixed "Análisis del partido" instead of translated insight. Fine for mock; weak for multilingual demo.

### M6 — Goal team via `scoring_team_id` only  · **medium (covered)**
`engine.py:186-191` correctly uses required `scoring_team_id` (earlier bug fixed). Keep test `test_goal_uses_required_scoring_team_without_optional_team_id`.

### M7 — CORS locked to localhost:5173  · **medium (Azure)**
`main.py:46`. Correct for local; Azure static URL will fail until env-driven allowlist (`CORS_ORIGINS`).

### M8 — No auth on kill / replay  · **medium (expected for hackathon)**
Anyone who can reach the API can burn CPU with kill+whatif. Acceptable offline; add rate limit or demo token before public Azure URL.

### M9 — salvage/ still in tree  · **medium**
`salvage/phase2/` (~27 files) includes **old api_key-oriented clients**. PLAN.md says remove once ported. Confuses reviewers and secret scanners.

**Fix:** Delete `salvage/` in a dedicated commit (content already ported).

### M10 — Schema `$id` / package paths after rename  · **medium**
Verify generated TS and JSON Schema `$id` strings say playmakers (Codex claimed yes). Spot-check in CI already diffs `src/generated`.

### M11 — WS playmakers path missing `replay_from_ms`  · **medium**
SSE supports `replay_from_ms`; WS does not (`main.py:174-207`). Kill-recover via WS incomplete.

### L1 — DeterministicMock lacks function invoking  · **low**
Runtime warning: "chat client does not support function invoking". MCP tools attached to writers are unused offline—by design.

### L2 — No path traversal on checkpoints  · **low (ok)**
Checkpoint dir is tempfile or operator-supplied, not query-param. No issue found.

### L3 — No secrets in live packages  · **low (ok)**
Live `model_clients.py` uses `DefaultAzureCredential`. Only salvage mentions `api_key`. `.env.example` placeholders only. `.env` gitignored.

### L4 — Open redirects  · **low (ok)**
Client-side `history.pushState` only; no server redirect.

### L5 — Injection  · **low (ok)**
Event payloads are structured Pydantic; LLM prompts are JSON dumps. KillSpec parsed strictly. No SQL.

### L6 — `speed=0` floods event loop  · **low**
Intentional for tests; with H1 caps and disconnect checks, acceptable.

### L7 — HANDOFF date still says 14 Oct in places  · **low**
Docs mostly updated for rename; a few timestamps stale.

---

## 2. Architecture & quality

**Strengths**
- Real Agent Framework `WorkflowBuilder` fan-out/fan-in (Stats → Tactics|Storyline → Compliance → Graphics → Audience).
- Compliance verifies metrics + evidence against StatsEngine (strong story for judges).
- MCP stats server dual-mode (standalone + mounted).
- Offline-first mock client; Azure clients gated on env.
- Typed Pydantic contracts + exported JSON Schema → TS types in CI.
- Kill/recover traces (`agent_down` → `fallback_on` → `restarted_from_checkpoint` → `caught_up`) are demo-ready.
- Calm UI + favicon/lockup present under `web/public` and `docs/brand`.

**Gaps**
- Agent Framework is used, but InsightExecutor still does a lot of bespoke timeout/circuit logic around `Agent.run`—fine, but Azure latency budgets untested.
- MCP enrichment is best-effort (`workflow.py:138-144` swallows all exceptions → silent fallback).
- Test coverage: workflow, kill, whatif, SSE/CORS, personalize well covered; **no** load test; **no** frontend stream integration test against real API in CI (only Playwright script manual); **no** test that seed/speed are bounded.
- Dead code: `salvage/`; possibly unused `/replay/sse` if UI only uses `/playmakers/*` (keep for debugging, document).
- Docs: rename landed; PLAN still schedules Dockerfiles in Phase 4 (accurate). No Dockerfile yet—expected.

---

## 3. Performance

| Issue | Notes |
|-------|--------|
| Cue volume | ~2 cues/event (tactics+storyline) × ~1569 events ≈ 3k+ cues/persona; ×2 streams. |
| What-If | 200 rollouts × 3 snapshots × ProcessPool(3); ~1–2s at triggers; evidence list is the silent killer (H2). |
| Frontend | `stream.ts` `setState` per message; no batching → React thrash at speed 50. Traces capped at 2400 (`stream.ts:81`); events/cues unbounded in memory. |
| Compliance | H3 O(n²). |
| Checkpoint I/O | H8. |

**Quick wins:** H2, H3, default web `whatif_rollouts=20`, batch UI updates with `requestAnimationFrame` or queue flush every 100ms.

---

## 4. Demo / production readiness

| Item | Status |
|------|--------|
| Offline mock | Solid; default path. |
| Azure OpenAI / Foundry clients | Implemented behind env; **never live-tested**. |
| `.env.example` | Present; document `CORS_ORIGINS`, `STATS_MCP_URL`, `VITE_API_BASE`. |
| Dockerfiles / compose | **Missing** (Phase 4). |
| `infra/main.bicep` | Stub only (logs, CAE, Cosmos placeholders)—do not `azd up` expecting a working app. |
| Favicon / logo | Integrated (`web/public/*`, About mark, header lockup). |
| CI | Python lint+test + web lint/test/build + generated types drift check. No e2e Playwright in CI. |
| Public GitHub | Not pushed (intentional). |

---

## 5. UX polish (code-level, not redesign)

- N1: Cap visible cues (keep highest priority N) to avoid overlay pile-up at 50×.
- N2: Show connection status ("reconnecting") in the Agents card footer.
- N3: Disable Start/Pause while `status !== "live"`.
- N4: Prefer named favourite in URL (`favourite=Okafor`) already; ensure Analyst metrics don't flicker to zeros between events.
- N5: `/about` Pause control already hidden—good; keep Replay controls from mutating About state.

---

## Recommended Codex prompts (medium+, after high fixes land)

```text
1) Shared session: change /playmakers/sse so one connection (or one backend job) serves multiple personas; update App.tsx to one stream filtered by persona. Keep kill/recover and What-If once per event.
2) Frontend stream batching: buffer SSE messages and flush to React state every 50–100ms; cap events/cues retained (e.g. last 2k events, active+recent cues only).
3) Incremental recovery storage; optional checkpoint every N events.
4) Env-driven CORS_ORIGINS; document Azure static web URL.
5) Add Playwright job to CI (install chromium, boot API+vite, npm run screenshot).
6) Phase 4 Dockerfiles + docker compose as in PLAN.md.
7) Soften compliance numeric-prose rules for jersey/clock patterns.
```

---

## Fixes applied in this review pass

Commit implements:
- **H1** Bound `seed` (0–10000) and `speed` (0–100) on SSE/WS.
- **H2** Cap What-If `evidence_event_ids` to last ≤8 (trigger last).
- **H3** Compliance validates against `StatsPacket` (O(1); kill-recover safe).
- **H4** Rebuild What-If pool on `BrokenProcessPool`; `_whatif_pool()` refreshes broken shared pools.
- **H5** Left to existing `aclosing` + StreamingResponse cancel (explicit `is_disconnected` broke TestClient streams).
- **H6** `app.state.whatif_pool = None` at import; safe getattr helper.
- **H7** `/replay/ws` handles `WebSocketDisconnect`.
- **M9** Deleted `salvage/`.
- **B1 mitigation** Web passes `whatif_rollouts=40` (full shared-session fix still open).
- Tests in `tests/test_review_fixes.py`.
