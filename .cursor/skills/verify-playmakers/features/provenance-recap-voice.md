# Provenance panel, full-time recap and voice

## Sub-features

- Provenance: each caption's Why? button (¿Por qué? in the Spanish fan view) opens an inline panel showing the agent, the Compliance verdict, supporting-event buttons and the stats used. Clicking an event rings it on the pitch. Close restores the captions.
- Recap: at full time each view replaces its captions with a recap that has the score headline, 4–6 moment buttons, Copy, Share and Why?.
- Voice: the toolbar's "Voice Off/On" button speaks priority fan moments through `speechSynthesis`, or through Azure AI Speech when `/speech/config` reports `azure: true`.

## How to get to it (user POV)

Start a replay. Click Why? under the analyst caption. For the recap, let a match finish (about 2.5 minutes at 50×). Switch Voice on before pressing Start.

## Driving it with Playwright

- Provenance: `page.locator(".analyst").getByRole("button", { name: "Why?" }).first().click()`, then `.analyst .provenance`.
- Recap: wait for `.casual .recap` (allow 400 s at 50×).
- Voice: headless Chromium has no voices. Stub `window.speechSynthesis` and `SpeechSynthesisUtterance` with `page.addInitScript` and record the utterances. A seed-7 run at 50× speaks about 9 lines.

## Gotchas

- The panel shows a snapshot of the cue. The live captions keep updating underneath and come back on Close.
- The Azure voice has not been tested against a live resource. With no env vars, `/speech/synthesize` returns 503 and the browser voice is used.
