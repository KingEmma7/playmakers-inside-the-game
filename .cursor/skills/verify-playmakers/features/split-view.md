# Split view

## Sub-features

- Analyst view (English, metrics) and fan view (Spanish by default, favourite player) side by side.
- Shared match clock and score bug. Replay speed and fan language controls. Press D to toggle broadcast safe areas.

## How to get to it (user POV)

Open the web root. Replay starts automatically.

## Driving it with Playwright

Select `50` in `REPLAY SPEED`. Wait for heading `Passing under pressure` in region `ANALYST view` and text `Follow the action as the match unfolds.` in region `FAN view` (the fan panel defaults to English), and for an Agents row reading `offline mock model`. Wait until `.shared-clock` reads at least `20:` and two `[data-testid="cue-card"]` elements exist.

## Gotchas

- The API allows CORS only from `http://localhost:<web port>`. Driving `127.0.0.1` makes the stream reconnect forever with no cues. `scripts/verify.sh` uses `localhost`.
- Both views share one server-side run per seed, so the two SSE connections must carry the same `viewer_profiles`.
