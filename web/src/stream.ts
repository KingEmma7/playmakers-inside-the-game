import { useEffect, useState } from "react";
import type { MatchEvent } from "./generated/MatchEvent";
import type { OverlayCue } from "./generated/OverlayCue";
import type { AgentTraceEvent } from "./generated/AgentTraceEvent";
import { parseStreamMessage } from "./parse";
declare global {
  interface Window {
    PLAYMAKERS_CONFIG?: { apiBase: string };
  }
}
export type { MatchEvent, OverlayCue, AgentTraceEvent };
export type Trace = AgentTraceEvent & { sequence: number; view: string };
export type Params = {
  session_id?: string;
  all_languages?: boolean;
  viewer_profiles?: string;
  seed: number;
  speed: number;
  persona: "analyst" | "casual";
  language: "en" | "es" | "fr";
  favourite_player_id?: string;
  kill?: string;
  replay_from_ms?: number;
  whatif_rollouts?: number;
};
export type Stream = {
  events: MatchEvent[];
  cues: OverlayCue[];
  traces: Trace[];
  status: string;
  generation: string;
  offline?: string;
};
const initial = (generation: string): Stream => ({
  events: [],
  cues: [],
  traces: [],
  status: "connecting",
  generation,
});
export const apiBaseUrl = () =>
  window.PLAYMAKERS_CONFIG?.apiBase || import.meta.env.VITE_API_BASE || "http://localhost:8000";
export function usePlaymakersStream(params: Params): Stream {
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
    let pendingEvents: MatchEvent[] = [];
    let pendingCues: OverlayCue[] = [];
    let pendingTraces: Trace[] = [];
    function flush() {
      if (!pendingEvents.length && !pendingCues.length && !pendingTraces.length)
        return;
      const events = pendingEvents;
      const cues = pendingCues;
      const traces = pendingTraces;
      pendingEvents = [];
      pendingCues = [];
      pendingTraces = [];
      setState((s) => {
        const retainedEvents = [...s.events, ...events].slice(-2500);
        const clock = retainedEvents.at(-1)?.clock_ms ?? 0;
        const allCues = [...s.cues, ...cues];
        const recent = new Set(allCues.slice(-400).map((c) => c.cue_id));
        return {
          ...s,
          events: retainedEvents,
          cues: allCues.filter(
            (c) => recent.has(c.cue_id) || clock < c.clock_ms + (c.duration_ms ?? 4000),
          ),
          traces: [...s.traces, ...traces].slice(-2400),
        };
      });
    }
    const batchTimer = setInterval(flush, 75);
    setState(initial(query));
    function connect() {
      const apiBase = apiBaseUrl();
      source = new EventSource(
        `${apiBase}/playmakers/sse?${query}`,
      );
      source.onopen = () => {
        delay = 1000;
        setState((s) => ({ ...s, status: "live" }));
      };
      source.onmessage = (message) => {
        if (disposed) return;
        const parsed = parseStreamMessage(message.data);
        if (parsed.kind === "event") {
          const event = parsed.event;
          duplicate = seen.has(event.sequence);
          lastSequence = event.sequence;
          if (duplicate) return;
          seen.add(event.sequence);
          completed = event.event_type === "period_end" && event.period === 2;
          pendingEvents.push(event);
        } else if (parsed.kind === "cue") {
          if (duplicate || cueIds.has(parsed.cue.cue_id)) return;
          cueIds.add(parsed.cue.cue_id);
          pendingCues.push(parsed.cue);
        } else if (parsed.kind === "trace") {
          if (duplicate) return;
          pendingTraces.push({
            ...parsed.trace, sequence: lastSequence, view: params.persona,
          });
        } else if (parsed.kind === "status") {
          const reason = parsed.model === "offline" ? parsed.reason : undefined;
          setState((s) => ({ ...s, offline: reason }));
        } else if (parsed.kind === "invalid") {
          setState((s) => ({ ...s, status: "invalid message" }));
        }
      };
      source.onerror = () => {
        source.close();
        flush();
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
      clearInterval(batchTimer);
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
