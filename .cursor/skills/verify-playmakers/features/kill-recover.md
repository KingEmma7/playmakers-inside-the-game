# Kill and recover

## Sub-features

- Stop Tactics mid-match. A template cue covers the gap, then the agent restarts from a checkpoint and catches up.
- Trace history shows `agent down`, `fallback on`, `restarted from checkpoint`, and `caught up` for both views (A and F).

## How to get to it (user POV)

During a replay, click **Stop Tactics agent** in the Agents panel, then open **Handoffs and recovery history**.

## Driving it with Playwright

Click the button matching `/Stop Tactics/`. Wait for `.agent-grid > div:nth-child(3) .recovering`. Click `Handoffs and recovery history`, then wait for each of the four actions in `.trace-row` rows whose `b span` reads `A` or `F`.

## Gotchas

- The journey allows up to 60 s for each recovery step.
