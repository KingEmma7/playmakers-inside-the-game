import type { AgentTraceEvent } from "./generated/AgentTraceEvent";
import type { MatchEvent } from "./generated/MatchEvent";
import type { OverlayCue } from "./generated/OverlayCue";

export type StreamMessage =
  | { kind: "event"; event: MatchEvent }
  | { kind: "cue"; cue: OverlayCue }
  | { kind: "trace"; trace: AgentTraceEvent }
  | { kind: "ignored" }
  | { kind: "invalid" };

type Fields = Record<string, unknown>;
const isObject = (value: unknown): value is Fields =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const strings = (data: Fields, ...keys: string[]) =>
  keys.every((key) => typeof data[key] === "string");
const numbers = (data: Fields, ...keys: string[]) =>
  keys.every((key) => typeof data[key] === "number" && Number.isFinite(data[key]));

const isMatchEvent = (data: Fields) =>
  strings(data, "event_id", "match_id", "event_type") &&
  numbers(data, "sequence", "clock_ms", "period");
const isOverlayCue = (data: Fields) =>
  strings(data, "cue_id", "template") &&
  numbers(data, "clock_ms") &&
  isObject(data.payload) &&
  Array.isArray(data.evidence_event_ids);
const isTrace = (data: Fields) =>
  strings(data, "agent", "action", "status") && numbers(data, "latency_ms");

export function parseStreamMessage(raw: string): StreamMessage {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return { kind: "invalid" };
  }
  if (!isObject(data)) return { kind: "invalid" };
  switch (data.type) {
    case "event":
      return isMatchEvent(data)
        ? { kind: "event", event: data as unknown as MatchEvent }
        : { kind: "invalid" };
    case "cue":
      return isOverlayCue(data)
        ? { kind: "cue", cue: data as unknown as OverlayCue }
        : { kind: "invalid" };
    case "trace":
      return isTrace(data)
        ? { kind: "trace", trace: data as unknown as AgentTraceEvent }
        : { kind: "invalid" };
    default:
      return { kind: "ignored" };
  }
}
