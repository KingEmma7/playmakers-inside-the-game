import { describe, expect, it } from "vitest";
import type { MatchEvent } from "./stream";
import { LENGTH, PitchModel, WIDTH, slot } from "./pitchModel";
import fixture from "./fixtures/seed7-events.json";

// A slice of the seed-7 PitchSim match (kickoff onwards, a goal and a substitution).
const events = fixture as unknown as MatchEvent[];
const FRAME = 16;

/** Replays the feed the way the app does: events arrive by match clock at `speed`, in 75 ms batches. */
function play(speed = 10, onFrame?: (m: PitchModel, before: Map<string, { x: number; y: number }>) => void) {
  const m = new PitchModel();
  let now = 0;
  let index = 0;
  let base = events[0].clock_ms;
  let lastClock = base;
  while (index < events.length) {
    if (now % 75 < FRAME) {
      const due: MatchEvent[] = [];
      while (index < events.length) {
        const e = events[index];
        // Skip the jumps between fixture slices instead of waiting through them.
        if (e.clock_ms - lastClock > 60_000) base += e.clock_ms - lastClock - 4000;
        if ((e.clock_ms - base) / speed > now) break;
        lastClock = e.clock_ms;
        due.push(e);
        index++;
      }
      if (due.length) m.sync(events.slice(0, index));
    }
    const before = new Map([...m.players].map(([id, p]) => [id, { x: p.x, y: p.y }]));
    m.step(FRAME);
    onFrame?.(m, before);
    now += FRAME;
  }
  return m;
}

describe("pitch model", () => {
  it("keeps every player on a stable id and never teleports anyone", () => {
    let worst = 0;
    const ids = new Set<string>();
    play(10, (m, before) => {
      for (const [id, p] of m.players) {
        ids.add(id);
        const was = before.get(id);
        if (was) worst = Math.max(worst, Math.hypot(p.x - was.x, p.y - was.y));
      }
      expect(m.players.size).toBe(22);
    });
    // At most ~2 m per 16 ms frame even while catching up: a fast run, never a jump.
    expect(worst).toBeLessThan(2.3);
    // 22 starters plus the substitutes who came on; nobody re-keyed by index.
    expect([...ids].filter((id) => Number(id.slice(1)) > 11).length).toBeGreaterThan(0);
    expect(ids.size).toBeLessThanOrEqual(22 + 6);
  });

  it.each([
    [10, 0.95],
    [50, 0.7],
  ])("keeps the ball on the pitch and delivers passes to the receiver at %ix", (speed, share) => {
    let arrivals = 0;
    let near = 0;
    let previousHolder: string | null = null;
    play(speed, (m) => {
      expect(m.ball.x).toBeGreaterThanOrEqual(-2.2);
      expect(m.ball.x).toBeLessThanOrEqual(LENGTH + 2.2);
      expect(m.ball.y).toBeGreaterThanOrEqual(0);
      expect(m.ball.y).toBeLessThanOrEqual(WIDTH);
      if (m.holder && m.holder !== previousHolder) {
        arrivals++;
        const p = m.players.get(m.holder);
        if (p && Math.hypot(p.x - m.ball.x, p.y - m.ball.y) < 3.5) near++;
      }
      previousHolder = m.holder;
    });
    expect(arrivals).toBeGreaterThan(100);
    // The receiver is at the ball when it arrives on nearly every pass.
    expect(near / arrivals).toBeGreaterThan(share);
  });

  it("puts both teams in their own half for kickoff and inside the lines everywhere", () => {
    const centre = { x: 52.5, y: 34 };
    for (let i = 0; i < 11; i++) {
      expect(slot(i, centre, "H", true, true).x).toBeLessThanOrEqual(52.5);
      expect(slot(i, centre, "A", false, true).x).toBeGreaterThanOrEqual(52.5);
    }
    for (let x = 0; x <= 105; x += 15)
      for (let y = 0; y <= 68; y += 17)
        for (let i = 0; i < 11; i++) {
          const s = slot(i, { x, y }, "A", true);
          expect(s.x).toBeGreaterThanOrEqual(0);
          expect(s.x).toBeLessThanOrEqual(105);
          expect(s.y).toBeGreaterThanOrEqual(3);
          expect(s.y).toBeLessThanOrEqual(65);
        }
  });

  it("settles instantly under reduced motion and after a reconnect flood", () => {
    const m = new PitchModel(true);
    m.sync(events.slice(0, 40));
    const last = events[39];
    expect(m.lastSequence).toBe(last.sequence);
    m.step(FRAME);
    const holder = m.holder && m.players.get(m.holder);
    if (holder) expect(Math.hypot(holder.x - m.ball.x, holder.y - m.ball.y)).toBeLessThan(1.5);
    const flood = new PitchModel();
    flood.sync(events.slice(0, 120));
    expect(flood.ballAlpha).toBe(1);
    flood.sync([]);
    expect(flood.lastSequence).toBe(-1);
  });
});
