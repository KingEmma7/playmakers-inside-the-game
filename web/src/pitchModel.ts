// Turns the PitchSim event feed into smooth, broadcast-style motion for the mini pitch.
// The shape constants mirror packages/pitchsim/src/pitchsim/shape.py; this is a
// formation-based visualisation around the real event positions, not tracking data.
import type { MatchEvent } from "./stream";
import type { Point } from "./geometry";

export const LENGTH = 105;
export const WIDTH = 68;
export type Side = "H" | "A";

const BASE_SHAPE: [number, number][] = [
  [5, 34],
  [24, 8],
  [21, 26],
  [21, 42],
  [24, 60],
  [36, 20],
  [33, 34],
  [36, 48],
  [47, 12],
  [50, 34],
  [47, 56],
];
const LINE_LIMITS: [number, number][] = [
  [2, 18],
  ...Array<[number, number]>(4).fill([5, 72]),
  ...Array<[number, number]>(3).fill([9, 88]),
  ...Array<[number, number]>(3).fill([20, 98]),
];

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const dist = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);
const lerp = (a: Point, b: Point, t: number): Point => ({
  x: a.x + (b.x - a.x) * t,
  y: a.y + (b.y - a.y) * t,
});
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const easeOut = (t: number) => 1 - (1 - t) ** 2;

/** Where shirt `index + 1` of `side` stands with the ball at `ball` (mirrors shape.slot). */
export function slot(
  index: number,
  ball: Point,
  side: Side,
  attacking: boolean,
  kickoff = false,
): Point {
  const home = side === "H";
  const bu = home ? ball.x : LENGTH - ball.x;
  const bv = home ? ball.y : WIDTH - ball.y;
  const [baseU, baseV] = BASE_SHAPE[index];
  const [lo, hi] = LINE_LIMITS[index];
  if (kickoff) {
    // Lined up for kickoff: the base shape itself, everyone in their own half.
    return home ? { x: baseU, y: baseV } : { x: LENGTH - baseU, y: WIDTH - baseV };
  }
  let u: number;
  let v: number;
  if (index === 0) {
    u = baseU + Math.max(0, bu - 30) * 0.12;
    v = 34 + (bv - 34) * 0.2;
  } else {
    u = baseU + (bu - 40) * 0.72 + (attacking ? 6 : -2);
    v = 34 + (baseV - 34) * 0.85 + (bv - 34) * 0.3;
  }
  u = clamp(u, lo, hi);
  v = clamp(v, 3, WIDTH - 3);
  return home ? { x: u, y: v } : { x: LENGTH - u, y: WIDTH - v };
}

export const code = (id: string | null | undefined) => id?.split("_").at(-1) ?? "";
const sideOf = (teamOrPlayer: string | null | undefined): Side | undefined => {
  if (!teamOrPlayer) return undefined;
  if (teamOrPlayer.endsWith("_HOME")) return "H";
  if (teamOrPlayer.endsWith("_AWAY")) return "A";
  const c = code(teamOrPlayer);
  return c.startsWith("H") ? "H" : c.startsWith("A") ? "A" : undefined;
};
const goalX = (attacking: Side) => (attacking === "H" ? LENGTH : 0);

export type PlayerDot = {
  id: string; // "H09"
  side: Side;
  shirt: number;
  x: number;
  y: number;
  alpha: number;
};

type Kind = "pass" | "carry" | "shot" | "loose" | "reset" | "hold";
type Segment = {
  kind: Kind;
  from: Point;
  to: Point;
  duration: number;
  elapsed: number;
  lift: number; // metres of visual height at mid-flight (long passes)
  receiver?: string;
  presser?: string;
  // Logical state applied when the ball arrives.
  holder?: string | null;
  possession?: Side;
};
export type Lane = { from: Point; to: Point; age: number; completed: boolean };

const PLAYER_TAU_MS = 420;
const HOLDER_TAU_MS = 70;
const MAX_SPEED_M_PER_S = 34; // visual metres per second (the replay runs faster than real time)
const FLOOD = 14;

export class PitchModel {
  players = new Map<string, PlayerDot>();
  lineup: Record<Side, string[]> = { H: [], A: [] };
  ball: Point = { x: LENGTH / 2, y: WIDTH / 2 };
  ballHeight = 0;
  ballAlpha = 0;
  holder: string | null = null;
  possession: Side = "H";
  kickoff = true;
  lanes: Lane[] = [];
  lastSequence = -1;
  matchId = "";
  private queue: Segment[] = [];
  private current?: Segment;
  private logicalBall: Point = { x: LENGTH / 2, y: WIDTH / 2 };
  private sinceArrive = 0;
  private hurry = 1;
  private tracked = new Map<string, Point>();
  private time = 0;

  constructor(public reduced = false) {
    this.reset("");
  }

  reset(matchId: string) {
    this.matchId = matchId;
    this.lastSequence = -1;
    this.queue = [];
    this.current = undefined;
    this.lanes = [];
    this.holder = null;
    this.possession = "H";
    this.kickoff = true;
    this.ball = { x: LENGTH / 2, y: WIDTH / 2 };
    this.logicalBall = { ...this.ball };
    this.ballAlpha = 0;
    this.ballHeight = 0;
    this.players.clear();
    this.tracked.clear();
    for (const side of ["H", "A"] as Side[]) {
      this.lineup[side] = Array.from({ length: 11 }, (_, i) => `${side}${String(i + 1).padStart(2, "0")}`);
      this.lineup[side].forEach((id, i) => {
        const p = slot(i, this.ball, side, false, true);
        this.players.set(id, { id, side, shirt: i + 1, x: p.x, y: p.y, alpha: 1 });
      });
    }
  }

  /** Feed every event up to the current one; older or repeated sequences are ignored. */
  sync(events: MatchEvent[]) {
    const last = events.at(-1);
    if (!last) {
      if (this.lastSequence >= 0) this.reset("");
      return;
    }
    if (last.match_id !== this.matchId || last.sequence < this.lastSequence) {
      this.reset(last.match_id);
    }
    const fresh = events.filter((e) => e.sequence > this.lastSequence);
    if (!fresh.length) return;
    const flood = fresh.length > FLOOD || (this.lastSequence < 0 && fresh.length > 3);
    for (const event of fresh) this.ingest(event);
    if (flood || this.reduced) this.settle();
  }

  /** Jump straight to the latest logical state (catch-up after a reconnect, or reduced motion). */
  settle() {
    for (const s of [this.current, ...this.queue]) if (s) this.arrive(s);
    this.current = undefined;
    this.queue = [];
    this.ball = { ...this.logicalBall };
    this.ballHeight = 0;
    this.ballAlpha = this.lastSequence >= 0 ? 1 : 0;
    this.lanes = this.lanes.slice(-1);
    for (const p of this.players.values()) {
      const t = this.targetFor(p);
      p.x = t.x;
      p.y = t.y;
    }
  }

  private push(segment: Omit<Segment, "elapsed" | "lift"> & { lift?: number }) {
    const s: Segment = { lift: 0, ...segment, elapsed: 0 };
    this.queue.push(s);
    this.logicalBall = { ...s.to };
  }

  private goTo(to: Point, kind: Kind = "loose") {
    const gap = dist(this.logicalBall, to);
    if (gap < 0.5) return;
    this.push({ kind, from: { ...this.logicalBall }, to, duration: clamp(160 + gap * 22, 200, 700) });
  }

  ingest(event: MatchEvent) {
    this.lastSequence = event.sequence;
    this.matchId = event.match_id;
    switch (event.event_type) {
      case "kickoff": {
        const side = sideOf(event.team_id) ?? "H";
        this.push({
          kind: "reset",
          from: { ...this.logicalBall },
          to: event.start_position,
          duration: 700,
          holder: this.lineup[side][9],
          possession: side,
        });
        this.kickoff = true;
        break;
      }
      case "pass": {
        const side = sideOf(event.team_id) ?? "H";
        this.goTo(event.start_position);
        const d = dist(event.start_position, event.end_position);
        this.push({
          kind: "pass",
          from: event.start_position,
          to: event.end_position,
          duration: clamp(240 + d * 20, 300, 1000),
          lift: d > 28 ? Math.min(6, d / 7) : 0,
          receiver: event.completed ? code(event.to_player_id) : undefined,
          holder: event.completed ? code(event.to_player_id) : null,
          possession: side,
        });
        this.lanes.push({ from: event.start_position, to: event.end_position, age: -1, completed: event.completed });
        this.lanes = this.lanes.slice(-3);
        break;
      }
      case "carry": {
        this.goTo(event.start_position);
        const d = dist(event.start_position, event.end_position);
        this.push({
          kind: "carry",
          from: event.start_position,
          to: event.end_position,
          duration: clamp(260 + d * 45, 320, 900),
          holder: code(event.player_id),
          possession: sideOf(event.team_id),
        });
        break;
      }
      case "shot": {
        const side = sideOf(event.team_id) ?? "H";
        this.goTo(event.position);
        const gx = goalX(side);
        const into = side === "H" ? 1 : -1;
        const aim = clamp(34 + (event.position.y - 34) * 0.12, 31, 37);
        const wide = event.position.y >= 34 ? 1 : -1;
        const to: Point =
          event.outcome === "goal"
            ? { x: gx + into * 1.4, y: aim }
            : event.outcome === "saved"
              ? { x: gx - into * 1.2, y: clamp(aim, 32.5, 35.5) }
              : event.outcome === "woodwork"
                ? { x: gx, y: 34 + wide * 3.66 }
                : event.outcome === "off_target"
                  ? { x: gx, y: 34 + wide * 6.5 }
                  : lerp(event.position, { x: gx, y: 34 }, 3 / Math.max(3, dist(event.position, { x: gx, y: 34 })));
        this.push({
          kind: "shot",
          from: event.position,
          to,
          duration: event.outcome === "blocked" ? 260 : 480,
          lift: event.outcome === "off_target" ? 1.5 : 0.6,
          holder: null,
        });
        break;
      }
      case "goal":
        this.push({ kind: "hold", from: { ...this.logicalBall }, to: { ...this.logicalBall }, duration: 900 });
        break;
      case "possession_change": {
        const side = sideOf(event.to_team_id ?? event.team_id) ?? this.possession;
        const holder = code(event.player_id) || null;
        const restart = event.reason === "goal_kickoff" || event.reason === "goal_kick";
        if (restart) {
          this.push({
            kind: "reset",
            from: { ...this.logicalBall },
            to: event.ball_position,
            duration: 800,
            holder,
            possession: side,
          });
          if (event.reason === "goal_kickoff") this.kickoff = true;
        } else {
          const gap = dist(this.logicalBall, event.ball_position);
          this.push({
            kind: "loose",
            from: { ...this.logicalBall },
            to: event.ball_position,
            duration: clamp(180 + gap * 26, 220, 700),
            receiver: holder ?? undefined,
            holder,
            possession: side,
          });
        }
        break;
      }
      case "tackle":
        this.goTo(event.position);
        this.push({ kind: "hold", from: event.position, to: event.position, duration: 260, presser: code(event.tackler_player_id) });
        break;
      case "foul":
        this.goTo(event.position);
        this.push({ kind: "hold", from: event.position, to: event.position, duration: 420, presser: code(event.fouler_player_id) });
        break;
      case "substitution": {
        const side = sideOf(event.team_id) ?? "H";
        const out = code(event.player_out_id);
        const incoming = code(event.player_in_id);
        const index = this.lineup[side].indexOf(out);
        const leaving = this.players.get(out);
        if (index >= 0 && leaving) {
          this.lineup[side][index] = incoming;
          this.players.delete(out);
          this.players.set(incoming, {
            id: incoming,
            side,
            shirt: Number(incoming.slice(1)),
            x: leaving.x,
            y: leaving.y,
            alpha: 0,
          });
        }
        break;
      }
      case "tracking_frame":
        // Real positions win over the formation whenever a feed provides them.
        for (const t of event.players) this.tracked.set(code(t.player_id), t.position);
        this.goTo(event.ball_position);
        break;
      case "period_end":
        this.push({ kind: "hold", from: { ...this.logicalBall }, to: { ...this.logicalBall }, duration: 600, holder: null });
        break;
      default:
        break;
    }
  }

  private arrive(s: Segment) {
    if (s.holder !== undefined) this.holder = s.holder;
    if (s.possession) this.possession = s.possession;
    if (s.kind === "pass" || s.kind === "carry" || s.kind === "loose") this.kickoff = false;
  }

  /** The ball segment in flight, if any (for drawing the pass line). */
  get flight(): { kind: Kind; from: Point; to: Point; t: number; receiver?: string } | undefined {
    const s = this.current;
    return s && { kind: s.kind, from: s.from, to: s.to, t: s.duration ? s.elapsed / s.duration : 1, receiver: s.receiver };
  }

  private focus(): Point {
    return this.current && this.current.kind !== "reset" ? this.current.to : this.ball;
  }

  private targetFor(p: PlayerDot): Point {
    const s = this.current;
    if (s?.receiver === p.id) return s.to;
    // Anticipate: the next receiver starts the run before the ball is played.
    const upcoming = this.queue.find((q) => q.receiver === p.id);
    if (upcoming && !(this.holder === p.id && s)) return upcoming.to;
    if (s?.presser === p.id) return { x: s.to.x + (p.side === "H" ? -0.9 : 0.9), y: s.to.y + 0.6 };
    if (this.holder === p.id && (!s || s.kind === "carry" || s.kind === "hold")) {
      return { x: this.ball.x + (p.side === "H" ? -0.9 : 0.9), y: this.ball.y + 0.4 };
    }
    const tracked = this.tracked.get(p.id);
    if (tracked) return tracked;
    const index = this.lineup[p.side].indexOf(p.id);
    const attacking = p.side === this.possession;
    const base = slot(Math.max(0, index), this.focus(), p.side, attacking, this.kickoff);
    if (this.reduced || this.kickoff) return base;
    // Off-the-ball players keep adjusting a little, so a quiet spell never looks frozen.
    const phase = p.shirt * 1.7 + (p.side === "A" ? 2.3 : 0);
    return {
      x: base.x + Math.sin(this.time / 2300 + phase) * 0.9,
      y: base.y + Math.cos(this.time / 3100 + phase * 1.3) * 0.9,
    };
  }

  /** Advance the animation by `dt` milliseconds. */
  step(dt: number) {
    if (this.reduced) {
      this.settle();
      this.updateLanes(dt);
      return;
    }
    let left = dt;
    // Drain a backlog faster so the picture never falls far behind the feed.
    const hurry = 1 + Math.max(0, this.queue.length - 1) * 0.6;
    this.hurry = hurry;
    while (left > 0) {
      if (!this.current) {
        this.current = this.queue.shift();
        if (!this.current) break;
        if (this.current.kind === "pass") {
          const lane = this.lanes.find((l) => l.age < 0 && l.from.x === this.current?.from.x && l.from.y === this.current?.from.y);
          if (lane) lane.age = 0;
        }
      }
      const s = this.current;
      const need = (s.duration - s.elapsed) / hurry;
      const used = Math.min(left, need);
      s.elapsed += used * hurry;
      left -= used;
      const t = s.duration ? clamp(s.elapsed / s.duration, 0, 1) : 1;
      if (s.kind === "reset") {
        this.ballAlpha = t < 0.5 ? 1 - t * 2 : (t - 0.5) * 2;
        this.ball = t < 0.5 ? { ...s.from } : { ...s.to };
        this.ballHeight = 0;
      } else if (s.kind === "hold") {
        this.ball = { ...s.to };
        this.ballHeight = 0;
        this.ballAlpha = 1;
      } else {
        const k = s.kind === "shot" ? easeOut(t) : ease(t);
        this.ball = lerp(s.from, s.to, k);
        this.ballHeight = s.lift * Math.sin(Math.PI * t);
        this.ballAlpha = 1;
      }
      if (t >= 1) {
        this.arrive(s);
        this.current = undefined;
        this.sinceArrive = 0;
      }
    }
    this.sinceArrive += dt;
    this.time += dt;
    this.ball = { x: clamp(this.ball.x, -2.2, LENGTH + 2.2), y: clamp(this.ball.y, 0.4, WIDTH - 0.4) };
    this.movePlayers(dt);
    this.updateLanes(dt);
  }

  private movePlayers(dt: number) {
    for (const p of this.players.values()) {
      const target = this.targetFor(p);
      const s = this.current;
      const chasing = s?.receiver === p.id || this.queue.some((q) => q.receiver === p.id);
      const tau =
        this.holder === p.id && !s
          ? HOLDER_TAU_MS
          : chasing
            ? Math.max(50, s && s.receiver === p.id ? (s.duration - s.elapsed) / 3 : 160)
            : PLAYER_TAU_MS;
      const k = 1 - Math.exp(-dt / tau);
      let dx = (target.x - p.x) * k;
      let dy = (target.y - p.y) * k;
      const cap =
        (MAX_SPEED_M_PER_S * (chasing || this.holder === p.id ? 2 : 1) * Math.min(2, this.hurry) * dt) / 1000;
      const step = Math.hypot(dx, dy);
      if (step > cap) {
        dx *= cap / step;
        dy *= cap / step;
      }
      p.x = clamp(p.x + dx, 0.6, LENGTH - 0.6);
      p.y = clamp(p.y + dy, 0.6, WIDTH - 0.6);
      p.alpha = Math.min(1, p.alpha + dt / 400);
    }
  }

  private updateLanes(dt: number) {
    for (const lane of this.lanes) if (lane.age >= 0) lane.age += dt;
    this.lanes = this.lanes.filter((l) => l.age < 1400);
  }

  /** Up to two open teammates ahead of the player on the ball, for faint passing-option lanes. */
  options(): PlayerDot[] {
    if (!this.holder || this.current || this.sinceArrive < 150) return [];
    const holder = this.players.get(this.holder);
    if (!holder) return [];
    const forward = holder.side === "H" ? 1 : -1;
    return [...this.players.values()]
      .filter((p) => p.side === holder.side && p.id !== holder.id && p.shirt !== 1)
      .filter((p) => (p.x - holder.x) * forward > -4)
      .map((p) => ({ p, d: dist(p, holder) }))
      .filter(({ d }) => d > 6 && d < 32)
      .sort((a, b) => a.d - b.d)
      .slice(0, 2)
      .map(({ p }) => p);
  }
}
