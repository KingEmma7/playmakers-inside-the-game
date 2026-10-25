// Convert a local /playmakers/sse JSONL recording into the compact timeline fixture.
// Each JSONL message must include wall_ms (monotonic milliseconds since connection).
// Usage: node scripts/commentary-record.mjs --record (local API on port 8020, ~10 minutes)
// Or: node scripts/commentary-record.mjs ../artifacts/commentary/seed382-timed.jsonl
import { readFileSync, writeFileSync } from "node:fs";
import { createServer } from "vite";
import { performance } from "node:perf_hooks";
async function record() {
  const profiles = [{ persona: "analyst", language: "en" },
    { persona: "casual", language: "en", favorite_player_id: "match_382_H09" }];
  const query = new URLSearchParams({ seed: "382", speed: "10", persona: "casual", language: "en",
    favourite_player_id: "match_382_H09", viewer_profiles: JSON.stringify(profiles) });
  const start = performance.now();
  const response = await fetch(`http://127.0.0.1:8020/playmakers/sse?${query}`);
  if (!response.ok || !response.body) throw new Error(`Local API: ${response.status}`);
  const messages = [];
  let buffer = "";
  for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
    buffer += chunk;
    const rows = buffer.split("\n");
    buffer = rows.pop();
    for (const row of rows) {
      if (row.startsWith("data: ")) messages.push({ ...JSON.parse(row.slice(6)), wall_ms: Math.round(performance.now() - start) });
    }
  }
  return messages;
}
const server = await createServer({ server: { middlewareMode: true } });
try {
  const { spokenLine, priorityMoment } = await server.ssrLoadModule("/src/voice.ts");
  const messages = process.argv[2] === "--record" ? await record() :
    readFileSync(process.argv[2], "utf8").trim().split("\n").map(row => JSON.parse(row));
  const events = [];
  const lines = [];
  const ids = new Map();
  const origin = messages.find(m => m.type === "event").wall_ms;
  let end = 0;
  for (const m of messages) {
    if (m.type === "event") { events.push(m); end = m.wall_ms - origin; }
    if (m.type !== "cue" || m.persona !== "casual" || m.language !== "en") continue;
    const moment = priorityMoment(m, events);
    if (!ids.has(m.cue_id)) ids.set(m.cue_id, ids.size);
    lines.push([m.clock_ms, m.wall_ms - origin, moment === "goal" ? "goal" : moment ? "big" : "normal", spokenLine(m, events), ids.get(m.cue_id)]);
  }
  if (events.at(-1)?.event_type !== "period_end" || events.at(-1)?.period !== 2)
    throw new Error("Recording does not include full time");
  const fixture = { source: "Local offline API, seed 382, speed 10, default H09 fan profile; actual wall offsets. Each row: clock_ms, wall_ms, emphasis (normal = routine), speech text, cue identity.", end, lines };
  writeFileSync("src/test-fixtures/commentary-382.json", JSON.stringify(fixture).replaceAll("],[", "],\n[") + "\n");
  console.info(`${lines.length} cues, ${end / 1000}s from kickoff to full time`);
} finally { await server.close(); }
