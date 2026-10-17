import type { MatchEvent } from "./stream";
export type Point = { x: number; y: number };
export function eventPoint(event?: MatchEvent): Point | undefined {
  if (!event) return undefined;
  if ("end_position" in event) return event.end_position;
  if ("ball_position" in event) return event.ball_position;
  if ("position" in event) return event.position;
  if ("start_position" in event) return event.start_position;
  return undefined;
}
