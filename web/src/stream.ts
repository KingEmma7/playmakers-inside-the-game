import { useEffect, useState } from "react";
import type { MatchEvent } from "./generated/MatchEvent";
import type { OverlayCue } from "./generated/OverlayCue";
import type { AgentTraceEvent } from "./generated/AgentTraceEvent";
export type { MatchEvent, OverlayCue, AgentTraceEvent };
export type Trace = AgentTraceEvent & { sequence: number; view: string };
export type Params = {
  seed: number;
  speed: number;
  persona: "analyst" | "casual";
  language: "en" | "es" | "fr";
  favourite_player_id?: string;
  kill?: string;
  replay_from_ms?: number;
};
export type Stream = {
  events: MatchEvent[];
  cues: OverlayCue[];
  traces: Trace[];
  status: string;
  generation: string;
};
const initial = (generation: string): Stream => ({
  events: [],
  cues: [],
  traces: [],
  status: "connecting",
  generation,
});
export function useGalleryStream(params: Params): Stream {
  const query = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => [k, String(v)]),
  ).toString();
  const [state, setState] = useState<Stream>(() => initial(query));
  useEffect(() => {
    let disposed = false;
    let source: EventSource;
    let timer: ReturnType<typeof setTimeout>;
    let delay = 1000;
    let lastSequence = -1;
    let duplicate = false;
    let completed = false;
    const seen = new Set<number>();
    const cueIds = new Set<string>();
    setState(initial(query));
    function connect() {
      source = new EventSource(
        `${import.meta.env.VITE_API_BASE || "http://localhost:8000"}/gallery/sse?${query}`,
      );
      source.onopen = () => {
        delay = 1000;
        setState((s) => ({ ...s, status: "live" }));
      };
      source.onmessage = (message) => {
        if (disposed) return;
        try {
          const data = JSON.parse(message.data);
          if (data.type === "event") {
            const event = data as MatchEvent;
            duplicate = seen.has(event.sequence);
            lastSequence = event.sequence;
            if (duplicate) return;
            seen.add(event.sequence);
            completed = event.event_type === "period_end" && event.period === 2;
            setState((s) => ({ ...s, events: [...s.events, event] }));
          } else if (
            data.type === "cue" &&
            !duplicate &&
            !cueIds.has(data.cue_id)
          ) {
            cueIds.add(data.cue_id);
            setState((s) => ({ ...s, cues: [...s.cues, data] }));
          } else if (data.type === "trace" && !duplicate) {
            setState((s) => ({
              ...s,
              traces: [
                ...s.traces,
                { ...data, sequence: lastSequence, view: params.persona },
              ].slice(-2400),
            }));
          }
        } catch {
          setState((s) => ({ ...s, status: "invalid message" }));
        }
      };
      source.onerror = () => {
        source.close();
        if (disposed) return;
        if (completed) {
          setState((s) => ({ ...s, status: "full time" }));
          return;
        }
        setState((s) => ({ ...s, status: "reconnecting" }));
        // API sessions are ephemeral: reconnect replays the seed; deduplicate until caught up.
        timer = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 15000);
      };
    }
    connect();
    return () => {
      disposed = true;
      source.close();
      clearTimeout(timer);
    };
  }, [query, params.persona]);
  return state.generation === query ? state : initial(query);
}
export function activeCues(cues: OverlayCue[], clock: number): OverlayCue[] {
  return cues
    .filter(
      (c) =>
        c.clock_ms <= clock && clock < c.clock_ms + (c.duration_ms ?? 4000),
    )
    .sort(
      (a, b) =>
        (b.priority ?? 0) - (a.priority ?? 0) ||
        b.clock_ms - a.clock_ms ||
        b.cue_id.localeCompare(a.cue_id),
    );
}
export function agentStatus(trace: AgentTraceEvent): string {
  if (trace.action === "agent_down") return "down";
  if (trace.action === "fallback_on" || trace.status === "fallback")
    return "fallback";
  if (trace.action === "restarted_from_checkpoint") return "recovering";
  if (trace.action === "caught_up") return "up";
  return trace.status === "error"
    ? "down"
    : trace.status === "retry"
      ? "recovering"
      : "up";
}
export const clockLabel = (clock: number) =>
  `${String(Math.floor(clock / 60000)).padStart(2, "0")}:${String(Math.floor(clock / 1000) % 60).padStart(2, "0")}`;
