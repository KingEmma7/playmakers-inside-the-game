import { useEffect, useRef } from "react";
import type { MatchEvent } from "./stream";
import type { Point } from "./geometry";
import { LENGTH, PitchModel, WIDTH } from "./pitchModel";

// Canvas units: 10 per metre plus a margin so the goals and touchline players are never clipped.
const SCALE = 10;
const MARGIN = 36;
export const CANVAS_W = LENGTH * SCALE + MARGIN * 2;
export const CANVAS_H = WIDTH * SCALE + MARGIN * 2;
const px = (m: number) => MARGIN + m * SCALE;

const INK = "#1D1D1F";
const LINE = "#FFFFFF";
const GRASS = "#E3ECE4";
const GRASS_ALT = "#DCE7DE";
const HOME = "#1F3FA8";
const AWAY = "#C98A00";
const FOLLOW = "#2442B5";
const RED = "#C4282D";

function drawPitch(ctx: CanvasRenderingContext2D) {
  ctx.fillStyle = GRASS;
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  // Mowing bands: flat alternating tones, no gradient.
  ctx.fillStyle = GRASS_ALT;
  for (let i = 0; i < 14; i += 2) ctx.fillRect(px((LENGTH / 14) * i), px(0), (LENGTH / 14) * SCALE, WIDTH * SCALE);
  ctx.strokeStyle = LINE;
  ctx.lineWidth = 3;
  ctx.strokeRect(px(0), px(0), LENGTH * SCALE, WIDTH * SCALE);
  ctx.beginPath();
  ctx.moveTo(px(LENGTH / 2), px(0));
  ctx.lineTo(px(LENGTH / 2), px(WIDTH));
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(px(LENGTH / 2), px(WIDTH / 2), 9.15 * SCALE, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = LINE;
  const spot = (x: number, y: number) => {
    ctx.beginPath();
    ctx.arc(px(x), px(y), 4, 0, Math.PI * 2);
    ctx.fill();
  };
  spot(LENGTH / 2, WIDTH / 2);
  for (const end of [0, 1]) {
    const dir = end ? -1 : 1;
    const line = end ? LENGTH : 0;
    const box = (depth: number, width: number) => {
      const x = end ? line - depth : line;
      ctx.strokeRect(px(x), px(WIDTH / 2 - width / 2), depth * SCALE, width * SCALE);
    };
    box(16.5, 40.32);
    box(5.5, 18.32);
    spot(line + dir * 11, WIDTH / 2);
    // Penalty arc: the part of the 9.15 m circle outside the box.
    const a = Math.acos(5.5 / 9.15);
    ctx.beginPath();
    if (end) ctx.arc(px(LENGTH - 11), px(WIDTH / 2), 9.15 * SCALE, Math.PI - a, Math.PI + a);
    else ctx.arc(px(11), px(WIDTH / 2), 9.15 * SCALE, -a, a);
    ctx.stroke();
    // Goal, drawn behind the line.
    ctx.save();
    ctx.strokeStyle = "#B9C4BB";
    ctx.lineWidth = 2;
    const gx = end ? px(LENGTH) : px(0) - 2 * SCALE;
    ctx.fillStyle = "#F4F7F4";
    ctx.fillRect(gx, px(WIDTH / 2 - 3.66), 2 * SCALE, 7.32 * SCALE);
    ctx.strokeRect(gx, px(WIDTH / 2 - 3.66), 2 * SCALE, 7.32 * SCALE);
    ctx.restore();
  }
  for (const [x, y, from] of [
    [0, 0, 0],
    [LENGTH, 0, Math.PI / 2],
    [LENGTH, WIDTH, Math.PI],
    [0, WIDTH, (Math.PI * 3) / 2],
  ]) {
    ctx.beginPath();
    ctx.arc(px(x), px(y), 1 * SCALE, from, from + Math.PI / 2);
    ctx.stroke();
  }
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number) {
  ctx.font = "500 24px Inter";
  const width = ctx.measureText(text).width + 28;
  const left = Math.max(10, Math.min(CANVAS_W - width - 10, x + 30));
  const top = Math.max(10, y - 78);
  ctx.fillStyle = "#FFFFFF";
  ctx.strokeStyle = "#D2D2D7";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(left, top, width, 50, 14);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = INK;
  ctx.textAlign = "left";
  ctx.fillText(text, left + 14, top + 33);
}

export default function Pitch({
  events = [],
  running,
  favourite,
  involvement = "",
  trail = [],
}: {
  events?: MatchEvent[];
  running: boolean;
  favourite?: string;
  involvement?: string;
  trail?: Point[];
  connect?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const model = useRef<PitchModel>(null);
  const props = useRef({ running, favourite, involvement, trail });
  useEffect(() => {
    props.current = { running, favourite, involvement, trail };
  }, [running, favourite, involvement, trail]);
  if (!model.current) {
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    model.current = new PitchModel(Boolean(reduced));
  }
  useEffect(() => {
    model.current?.sync(events);
  }, [events]);
  useEffect(() => {
    const ctx = canvas.current?.getContext("2d");
    const m = model.current;
    if (!ctx || !m) return;
    const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const onMotion = () => (m.reduced = Boolean(motion?.matches));
    motion?.addEventListener?.("change", onMotion);
    let frame = 0;
    let previous = 0;
    function draw(time: number) {
      if (!ctx || !m) return;
      const dt = Math.min(64, previous ? time - previous : 16);
      previous = time;
      const { running, favourite, involvement, trail } = props.current;
      if (running) m.step(dt);
      drawPitch(ctx);
      const live = m.lastSequence >= 0;

      // Pass lines: only the real pass, passer to target, fading once the ball has arrived.
      for (const lane of m.lanes) {
        if (lane.age < 0) continue;
        const flight = m.flight;
        const inFlight = flight?.kind === "pass" && flight.from.x === lane.from.x && flight.from.y === lane.from.y;
        const alpha = inFlight ? 0.45 : Math.max(0, 0.45 * (1 - lane.age / 1400));
        if (alpha <= 0.01) continue;
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = INK;
        ctx.lineWidth = 2;
        ctx.setLineDash(lane.completed ? [] : [8, 8]);
        ctx.beginPath();
        ctx.moveTo(px(lane.from.x), px(lane.from.y));
        ctx.lineTo(px(lane.to.x), px(lane.to.y));
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // Passing options: faint lanes from the player on the ball to nearby teammates.
      const carrier = m.holder ? m.players.get(m.holder) : undefined;
      if (carrier) {
        ctx.globalAlpha = 0.16;
        ctx.strokeStyle = INK;
        ctx.lineWidth = 1.5;
        for (const p of m.options()) {
          ctx.beginPath();
          ctx.moveTo(px(carrier.x), px(carrier.y));
          ctx.lineTo(px(p.x), px(p.y));
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;

      // Evidence for Why?, the recap and What-If: numbered rings at the real event positions.
      trail.forEach((p, i) => {
        const last = i === trail.length - 1;
        const x = px(Math.max(0, Math.min(LENGTH, p.x)));
        const y = px(Math.max(0, Math.min(WIDTH, p.y)));
        // Dashed so a marked spot never reads as the ball.
        ctx.strokeStyle = last ? RED : "#737378";
        ctx.lineWidth = last ? 3 : 2;
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.arc(x, y, last ? 26 : 22, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        if (trail.length > 1) {
          ctx.fillStyle = last ? RED : "#515154";
          ctx.font = "600 15px Inter";
          ctx.textAlign = "center";
          ctx.fillText(String(i + 1), x + (last ? 24 : 20), y - (last ? 20 : 16));
        }
      });

      for (const p of m.players.values()) {
        const x = px(p.x);
        const y = px(p.y);
        const onBall = p.id === m.holder;
        ctx.globalAlpha = (live ? 1 : 0.35) * p.alpha;
        if (favourite === p.id && live) {
          ctx.strokeStyle = FOLLOW;
          ctx.lineWidth = 3;
          ctx.beginPath();
          ctx.arc(x, y, 25, 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.fillStyle = p.side === "H" ? HOME : AWAY;
        ctx.strokeStyle = "#FFFFFF";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, onBall ? 17 : 15, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = p.side === "H" ? "#FFFFFF" : INK;
        ctx.font = "600 14px Inter";
        ctx.textAlign = "center";
        ctx.fillText(String(p.shirt), x, y + 5);
      }
      ctx.globalAlpha = 1;

      if (live && m.ballAlpha > 0.01) {
        const bx = px(m.ball.x);
        const by = px(m.ball.y);
        const lift = m.ballHeight * SCALE * 0.9;
        ctx.globalAlpha = m.ballAlpha * 0.22;
        ctx.fillStyle = INK;
        ctx.beginPath();
        ctx.ellipse(bx + 2, by + 4, 9, 4.5, 0, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = m.ballAlpha;
        ctx.fillStyle = "#FFFFFF";
        ctx.strokeStyle = INK;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(bx, by - lift, 9.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = INK;
        ctx.beginPath();
        ctx.arc(bx, by - lift, 3.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      if (favourite && live) {
        const p = m.players.get(favourite);
        if (p && involvement) label(ctx, involvement, px(p.x), px(p.y));
      }
      frame = requestAnimationFrame(draw);
    }
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      motion?.removeEventListener?.("change", onMotion);
    };
  }, []);
  return (
    <canvas
      ref={canvas}
      width={CANVAS_W}
      height={CANVAS_H}
      aria-label="Synthetic football pitch with 22 players and ball"
    />
  );
}
