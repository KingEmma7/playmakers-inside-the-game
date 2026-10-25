import { mkdirSync, writeFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import { CommentaryQueue, SpeechBusy, type Speaker, type CommentaryLine } from "./voice";
import { BaselineCommentaryQueue } from "./test-fixtures/voice-before";
import recording from "./test-fixtures/commentary-382.json";

type Arrival = CommentaryLine & { wall_ms: number; clock_ms: number };
function fixture(): { lines: Arrival[]; end: number } {
  const lines = recording.lines.map(row => {
    const [clock_ms, wall_ms, emphasis, text, id] = row as [number, number, CommentaryLine["emphasis"], string, number];
    return { id: String(id), clock_ms, wall_ms, emphasis, text, language: "en" as const,
      priority: emphasis === "normal" ? "routine" as const : "key" as const };
  });
  return { lines, end: recording.end };
}

afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });
async function measure(Queue: typeof CommentaryQueue | typeof BaselineCommentaryQueue, speed = 10, name = Queue.name, transientBusy = false, browser = false) {
  vi.useFakeTimers(); vi.setSystemTime(0);
  const source = fixture();
  const lines = source.lines.map(line => ({ ...line, wall_ms: line.wall_ms * 10 / speed }));
  const end = source.end * 10 / speed;
  const intervals: { start: number; end: number; text: string }[] = [];
  let tokens = 18, updated = 0, requests = 0, busy = 0, chars = 0, refused = false;
  const speaker: Speaker = {
    name: browser ? "browser" : "azure", routineIntervalMs: 3400,
    async speak(text, language, emphasis) {
      const clip = await this.prepare!(text, language, emphasis);
      try { await clip.play(); } finally { clip.dispose(); }
    },
    async prepare(text) {
      const now = Date.now(); tokens = Math.min(18, tokens + (now - updated) * 18 / 60000); updated = now;
      requests++;
      if ((!browser && tokens < 1) || (transientBusy && !refused && now >= 60000)) { refused = true; busy++; throw new SpeechBusy(); }
      if (!browser) tokens--; chars += text.length;
      if (!browser) await new Promise(resolve => setTimeout(resolve, 400));
      const durationMs = (text.length / 14.5 + .3) * 1000;
      return { durationMs, async play() {
        intervals.push({ start: Date.now(), end: Date.now() + durationMs, text });
        await new Promise(resolve => setTimeout(resolve, durationMs));
      }, dispose() {} };
    }, cancel() {},
  };
  if (browser) {
    const prepare = speaker.prepare!;
    speaker.speak = async (text, language, emphasis) => {
      const clip = await prepare.call(speaker, text, language, emphasis);
      await clip.play();
    };
    delete speaker.prepare;
  }
  const queue = new Queue(speaker, () => Date.now());
  queue.setSpeed(speed);
  const timer = setInterval(() => queue.tick(), 250);
  for (const line of lines) setTimeout(() => { queue.enqueue(line); queue.tick(); }, line.wall_ms);
  await vi.advanceTimersByTimeAsync(end);
  clearInterval(timer); queue.clear();
  let cursor = 0, speaking = 0;
  const gaps: number[] = [];
  for (const interval of intervals) {
    if (interval.start >= end) break;
    if (interval.start > cursor) gaps.push(interval.start - cursor);
    speaking += Math.max(0, Math.min(end, interval.end) - Math.max(cursor, interval.start));
    cursor = Math.max(cursor, Math.min(end, interval.end));
  }
  if (cursor < end) gaps.push(end - cursor);
  gaps.sort((a,b) => a-b);
  const percentile = (p: number) => (gaps[Math.ceil(p * gaps.length) - 1] ?? 0) / 1000;
  const durations = intervals.map(i => (i.end - i.start) / 1000).sort((a,b) => a-b);
  const report = { audioMedian: durations[Math.floor(durations.length / 2)], seconds: end / 1000, cues: lines.length, requests, busy, chars,
    spoken: queue.stats.spoken, dropped: queue.stats.dropped,
    max: percentile(1), p95: percentile(.95), median: percentile(.5), speaking: speaking / end * 100 };
  mkdirSync("../artifacts/commentary", { recursive: true });
  writeFileSync(`../artifacts/commentary/${name}.json`, JSON.stringify(report, null, 2));
  return report;
}
it("measures the pre-fix seed-382 Azure path", async () => { await measure(BaselineCommentaryQueue); }, 20000);
it("measures continuous seed-382 Azure commentary", async () => {
  const report = await measure(CommentaryQueue);
  expect(report.max).toBeLessThanOrEqual(3.5);
  expect(report.audioMedian).toBeGreaterThanOrEqual(3.5);
  expect(report.audioMedian).toBeLessThanOrEqual(5);
  expect(report.requests / report.seconds * 60).toBeLessThanOrEqual(18);
  expect(report.busy).toBe(0);
  expect(report.speaking).toBeGreaterThan(95);
  expect(report.chars).toBeLessThan(60000);
}, 20000);

it("quantifies the intentional key-only policy at 50x", async () => {
  const report = await measure(BaselineCommentaryQueue, 50, "baseline-50x");
  expect(report.max).toBeGreaterThan(10);
}, 20000);

it("measures a transient busy response without switching away from Azure", async () => {
  const before = await measure(BaselineCommentaryQueue, 10, "before-busy", true);
  const after = await measure(CommentaryQueue, 10, "after-busy", true);
  expect(before.busy).toBe(1);
  expect(after.busy).toBe(1);
  expect(after.max).toBeLessThanOrEqual(3.5);
}, 20000);
it("keeps browser fallback continuous without Azure pacing", async () => {
  const report = await measure(CommentaryQueue, 10, "browser", false, true);
  expect(report.max).toBeLessThanOrEqual(3.5);
}, 20000);
