import { useEffect, useRef } from "react";
import { playerName } from "./players";
import type { MatchEvent } from "./stream";
type Point = { x: number; y: number };
function ballFor(event?: MatchEvent): Point | undefined {
  if (!event) return undefined;
  if ("end_position" in event) return event.end_position;
  if ("ball_position" in event) return event.ball_position;
  if ("position" in event) return event.position;
  if ("start_position" in event) return event.start_position;
  return undefined;
}
export default function Pitch({
  event,
  running,
  favourite,
  shots = 0,
}: {
  event?: MatchEvent;
  running: boolean;
  favourite?: string;
  shots?: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const current = useRef<Point>({ x: 52.5, y: 34 });
  const target = useRef({ event, running, favourite, shots });
  useEffect(() => {
    target.current = { event, running, favourite, shots };
  }, [event, running, favourite, shots]);
  useEffect(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    let frame = 0;
    let previous = 0;
    function draw(time: number) {
      if (!ctx) return;
      const dt = Math.min(50, time - previous || 16);
      previous = time;
      const { event, running, favourite, shots } = target.current;
      const goal = ballFor(event) ?? current.current;
      if (running) {
        const blend = 1 - Math.exp(-dt / 180);
        current.current.x += (goal.x - current.current.x) * blend;
        current.current.y += (goal.y - current.current.y) * blend;
      }
      const w = 1050,
        h = 680;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#E6EFE7";
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = "#FFFFFF";
      ctx.lineWidth = 2;
      ctx.strokeRect(30, 30, 990, 620);
      ctx.beginPath();
      ctx.moveTo(525, 30);
      ctx.lineTo(525, 650);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(525, 340, 91.5, 0, Math.PI * 2);
      ctx.stroke();
      for (const x of [30, 855]) {
        ctx.strokeRect(x, 138.5, 165, 403);
        ctx.strokeRect(x === 30 ? 30 : 965, 248.5, 55, 183);
      }
      const ball = current.current;
      const tracking =
        event?.event_type === "tracking_frame" ? event.players : null;
      for (let team = 0; team < 2; team++) {
        for (let i = 0; i < 11; i++) {
          const tracked = tracking?.[team * 11 + i];
          const shape = [
            [7, 34],
            [22, 12],
            [20, 27],
            [21, 43],
            [24, 56],
            [39, 21],
            [42, 35],
            [38, 51],
            [59, 17],
            [62, 34],
            [57, 55],
          ];
          const [baseX, baseY] = shape[i];
          const seed = Number(event?.match_id.match(/\d+/)?.[0] || 7);
          const jitter = (axis: number) =>
            Math.sin((i + 1) * 17.3 + team * 29 + seed + axis * 43) * 2.5;
          let x =
            (team ? 105 - baseX : baseX) +
            (ball.x - 52.5) * (i ? 0.16 : 0.03) +
            jitter(0);
          let y = baseY + (ball.y - 34) * 0.13 + jitter(1);
          if (tracked) {
            x = tracked.position.x;
            y = tracked.position.y;
          }
          const actor =
            event &&
            ("shooter_player_id" in event
              ? event.shooter_player_id
              : "from_player_id" in event
                ? event.from_player_id
                : event.player_id);
          const active = actor?.endsWith(
            `${team ? "A" : "H"}${String(i + 1).padStart(2, "0")}`,
          );
          if (active && !tracked) {
            x = ball.x - 1.2;
            y = ball.y + 1.2;
          }
          const followed =
            favourite ===
            `${team ? "A" : "H"}${String(i + 1).padStart(2, "0")}`;
          if (followed) {
            ctx.strokeStyle = "#2442B5";
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.arc(x * 10, y * 10, 27, 0, Math.PI * 2);
            ctx.stroke();
            ctx.lineWidth = 2;
            const label = `${playerName(favourite!)} · ${shots} tiros`;
            ctx.font = "500 25px Inter";
            const width = ctx.measureText(label).width + 32;
            const left = Math.max(16, Math.min(1034 - width, x * 10 + 32));
            const top = Math.max(16, y * 10 - 82);
            ctx.fillStyle = "#FFFFFF";
            ctx.beginPath();
            ctx.roundRect(left, top, width, 56, 16);
            ctx.fill();
            ctx.fillStyle = "#1D1D1F";
            ctx.textAlign = "left";
            ctx.fillText(label, left + 16, top + 36);
          }
          ctx.shadowColor = "transparent";
          ctx.shadowBlur = 0;
          ctx.fillStyle = team ? "#FFFFFF" : "#1F3FA8";
          ctx.beginPath();
          ctx.arc(x * 10, y * 10, active ? 18 : 16, 0, Math.PI * 2);
          ctx.fill();
          ctx.strokeStyle = team ? "#C98A00" : "#FFFFFF";
          ctx.stroke();
          ctx.shadowBlur = 0;
          ctx.fillStyle = team ? "#7A5200" : "#FFFFFF";
          ctx.font = "600 13px Inter";
          ctx.textAlign = "center";
          ctx.fillText(String(i + 1), x * 10, y * 10 + 4);
        }
      }
      if (event?.event_type === "pass") {
        ctx.strokeStyle = "#1D1D1F";
        ctx.setLineDash([6, 8]);
        ctx.beginPath();
        ctx.moveTo(event.start_position.x * 10, event.start_position.y * 10);
        ctx.quadraticCurveTo(
          (event.start_position.x + event.end_position.x) * 5,
          (event.start_position.y + event.end_position.y) * 5 - 35,
          event.end_position.x * 10,
          event.end_position.y * 10,
        );
        ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.fillStyle = "#1D1D1F";
      ctx.beginPath();
      ctx.arc(ball.x * 10, ball.y * 10, 5, 0, Math.PI * 2);
      ctx.fill();
      frame = requestAnimationFrame(draw);
    }
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, []);
  return (
    <canvas
      ref={canvas}
      width={1050}
      height={680}
      aria-label="Synthetic football pitch with 22 players and ball"
    />
  );
}
