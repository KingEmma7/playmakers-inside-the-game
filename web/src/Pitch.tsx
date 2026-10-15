import { useEffect, useRef } from "react";
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
}: {
  event?: MatchEvent;
  running: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const current = useRef<Point>({ x: 52.5, y: 34 });
  const target = useRef({ event, running });
  useEffect(() => {
    target.current = { event, running };
  }, [event, running]);
  useEffect(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    let frame = 0;
    let previous = 0;
    function draw(time: number) {
      if (!ctx) return;
      const dt = Math.min(50, time - previous || 16);
      previous = time;
      const { event, running } = target.current;
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
          const row = i === 0 ? 0 : Math.ceil(i / 4);
          const baseX = i === 0 ? 7 : 15 + row * 16;
          const baseY = i === 0 ? 34 : 10 + ((i - 1) % 4) * 16;
          let x = (team ? 105 - baseX : baseX) + (ball.x - 52.5) * 0.16;
          let y = baseY + (ball.y - 34) * 0.13;
          if (tracked) {
            x = tracked.position.x;
            y = tracked.position.y;
          }
          const active = event?.player_id?.endsWith(
            `${team ? "A" : "H"}${String(i + 1).padStart(2, "0")}`,
          );
          if (active && !tracked) {
            x = ball.x - 1.2;
            y = ball.y + 1.2;
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
