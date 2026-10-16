---
name: verify-playmakers
description: "Drive the Playmakers web app (React split view on the FastAPI replay API) the way a viewer does and capture screenshot evidence. Use before claiming a backend, stream, or UI change works, or when CI's live browser job fails."
---

# Verify Playmakers

One command boots the API and the web app, runs the Playwright journey, saves evidence, and tears down what it started.

## Launch

```bash
scripts/verify.sh
```

Needs the README Quickstart done once (`.venv` with the six packages, `cd web && npm ci`, `npx playwright install chromium`). The script starts `uvicorn replay_api.main:app` on 127.0.0.1:8000 and Vite on 5173. It waits for `/healthz` and the web root, then runs `web/scripts/screenshot.mjs`. It exits 0 and prints `PASS. Evidence in artifacts/verify/<timestamp>` only when the whole journey passes.

Change ports with `PLAYMAKERS_API_PORT` and `PLAYMAKERS_WEB_PORT`. The script refuses to start if either port already answers, so it never drives someone else's instance.

## Doctor

```bash
scripts/verify.sh doctor
```

Read-only. It reports whether the API and web are up and whether Python packages and web deps are installed. Exit 0 means all four are fine. Run it first when anything looks off.

## Drive

The journey in `web/scripts/screenshot.mjs` uses stable handles:

- Speed select: label `REPLAY SPEED` (set to `50`).
- Views: regions `ANALYST view` and `FAN view`. Fan language: label `FAN LANGUAGE`.
- Shared clock: `.shared-clock`. Cue cards: `[data-testid="cue-card"]`. What-If card: `.casual .whatif`.
- Kill: button matching `/Stop Tactics/`. Trace history: text `Handoffs and recovery history`, rows `.trace-row` in role `log`.
- About: link `About`.

To drive a custom path, start the two Quickstart terminals yourself, then run `PLAYMAKERS_WEB_URL=http://localhost:5173 npm run screenshot --prefix web` or your own Playwright script.

## Evidence

Each run writes `artifacts/verify/<timestamp>/` (git-ignored) with `e2e-screenshot.png`, `main.png`, `kill.png`, `about.png`, `journey.txt`, `api.log`, `web.log`, and `doctor.txt`. The journey fails on any uncaught page error, layout overflow at 1920x1080 or 1440x900, or a missing agent-trace step. Compare `main.png` and `kill.png` against `web/shots/` for visual regressions. Live clock, player dots, and latencies differ slightly between runs. Layout and copy must not.

`scripts/verify.sh --update-shots` writes to the committed `web/shots/` and `web/e2e-screenshot.png` instead. Use it only when a visual change is intended.

## Cleanup

The script kills the two process groups it started on exit, including on failure. It never kills by name. Evidence stays in `artifacts/verify/`. Delete old runs with `rm -rf artifacts/verify`.

## Feature map

See [features/README.md](features/README.md).
