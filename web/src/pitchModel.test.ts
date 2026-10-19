import { describe, expect, it } from "vitest";
import type { MatchEvent } from "./stream";
import {
  LENGTH,
  PitchModel,
  WIDTH,
  passMs,
  realBallSpeed,
  slot,
} from "./pitchModel";
import parity from "./fixtures/slot-parity.json";
import fixture from "./fixtures/seed7-events.json";

// Two slices of the seed-7 PitchSim match: kickoff to just after the first goal, and a substitution.
const events = fixture as unknown as MatchEvent[];
const FRAME = 16;

/** Replays the feed the way the app does: events arrive by match clock at `speed`, in 75 ms batches. */
function play(
  speed = 10,
  onFrame?: (
    m: PitchModel,
    before: Map<string, { x: number; y: number }>,
  ) => void,
) {
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
        if (e.clock_ms - lastClock > 60_000)
          base += e.clock_ms - lastClock - 4000;
        if ((e.clock_ms - base) / speed > now) break;
        lastClock = e.clock_ms;
        due.push(e);
        index++;
      }
      if (due.length) m.sync(events.slice(0, index));
    }
    const before = new Map(
      [...m.players].map(([id, p]) => [id, { x: p.x, y: p.y }]),
    );
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
    expect(
      [...ids].filter((id) => Number(id.slice(1)) > 11).length,
    ).toBeGreaterThan(0);
    expect(ids.size).toBeLessThanOrEqual(22 + 6);
  });

  it.each([
    [10, 0.95],
    [50, 0.9],
  ])(
    "keeps the ball on the pitch and delivers passes to the receiver at %ix",
    (speed, share) => {
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
    },
  );

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
    if (holder)
      expect(Math.hypot(holder.x - m.ball.x, holder.y - m.ball.y)).toBeLessThan(
        1.5,
      );
    const flood = new PitchModel();
    flood.sync(events.slice(0, 120));
    expect(flood.ballAlpha).toBe(1);
    flood.sync([]);
    expect(flood.lastSequence).toBe(-1);
  });

  it("matches the Python team shape exactly (shape.slot)", () => {
    for (const [i, x, y, home, attacking, ex, ey] of parity as [
      number,
      number,
      number,
      boolean,
      boolean,
      number,
      number,
    ][]) {
      const p = slot(i, { x, y }, home ? "H" : "A", attacking);
      expect(p.x).toBeCloseTo(ex, 2);
      expect(p.y).toBeCloseTo(ey, 2);
    }
  });

  it("flies passes at real ball speeds: longer passes travel faster", () => {
    // Metrica sample games: p10 ~7 m/s, median ~12 m/s, p90 ~18 m/s.
    expect(realBallSpeed(5)).toBeGreaterThan(7);
    expect(realBallSpeed(14)).toBeCloseTo(11.9, 0);
    expect(realBallSpeed(27)).toBeGreaterThan(16);
    expect(passMs(30) / 30).toBeLessThan(passMs(8) / 8);
    expect(passMs(30)).toBeGreaterThan(passMs(8));
  });

  it("makes the keeper react to every shot the way the outcome says", () => {
    const shots = events.filter((e) => e.event_type === "shot");
    expect(shots.length).toBeGreaterThan(0);
    for (const outcome of ["saved", "goal", "off_target"] as const) {
      const m = new PitchModel();
      const index = events.findIndex((e) => e.event_type === "shot");
      const shot = { ...events[index], outcome } as MatchEvent;
      m.sync(events.slice(0, index));
      m.settle();
      const side = shot.team_id?.endsWith("_HOME") ? "A" : "H";
      const keeperId = m.lineup[side][0];
      const before = { ...m.players.get(keeperId)! };
      m.sync([...events.slice(0, index), shot]);
      let dived = 0;
      let reach = Infinity;
      for (let t = 0; t < 1200; t += FRAME) {
        m.step(FRAME);
        const k = m.players.get(keeperId)!;
        dived = Math.max(dived, k.dive);
        reach = Math.min(reach, Math.hypot(k.x - m.ball.x, k.y - m.ball.y));
        if (!m.flight) break;
      }
      const k = m.players.get(keeperId)!;
      const ballLine = Math.abs(m.ball.x - (side === "A" ? LENGTH : 0));
      if (outcome === "saved") {
        expect(dived).toBeGreaterThan(0.5);
        expect(Math.hypot(k.x - m.ball.x, k.y - m.ball.y)).toBeLessThan(1.5);
      } else if (outcome === "goal") {
        expect(dived).toBeGreaterThan(0.5);
        expect(Math.abs(k.y - before.y)).toBeGreaterThan(0.5); // he went for it
        expect(Math.abs(k.y - m.ball.y)).toBeGreaterThan(1); // and the ball beat him
        expect(ballLine).toBeLessThan(2);
      } else {
        expect(Math.abs(m.ball.y - 34)).toBeGreaterThan(3.66); // wide of the post
        expect(dived).toBeLessThan(0.1);
      }
      expect(reach).toBeGreaterThanOrEqual(0);
    }
  });

  it("tracks the ball laterally with the keeper and steps him out as play moves away", () => {
    const near = slot(0, { x: 15, y: 10 }, "H", false);
    const far = slot(0, { x: 80, y: 34 }, "H", false);
    const centre = slot(0, { x: 15, y: 34 }, "H", false);
    expect(near.y).toBeLessThan(centre.y - 0.5);
    expect(far.x).toBeGreaterThan(near.x + 3);
  });
});
