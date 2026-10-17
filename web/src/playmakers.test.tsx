import { act, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeCues,
  usePlaymakersStream,
  type OverlayCue,
  type Trace,
} from "./stream";
import { CueCard, ViewPanel } from "./Overlay";
import TracePanel from "./TracePanel";
import { parseStreamMessage } from "./parse";
import type { MatchEvent } from "./stream";
vi.mock("./Pitch", () => ({
  default: ({ trail = [] }: { trail?: { x: number; y: number }[] }) => (
    <div data-testid="pitch" data-trail={JSON.stringify(trail)} />
  ),
}));
const cue = (overrides: Partial<OverlayCue> = {}): OverlayCue => ({
  cue_id: "cue1",
  clock_ms: 1000,
  template: "storyline",
  duration_ms: 4000,
  priority: 0,
  evidence_event_ids: ["e1"],
  payload: {
    headline: "Pressure rising",
    detail: "Verified analysis",
    metrics: {},
  },
  ...overrides,
});
const wireEvent = (fields: Record<string, unknown>) => ({
  type: "event",
  schema_version: "1.0.0",
  event_id: `e${String(fields.sequence)}`,
  match_id: "match_7",
  clock_ms: 0,
  period: 1,
  event_type: "pass",
  labels: [],
  ...fields,
});
const trace = (overrides: Partial<Trace> = {}): Trace => ({
  agent: "tactics",
  action: "insight",
  latency_ms: 12.3,
  status: "ok",
  sequence: 1,
  view: "analyst",
  ...overrides,
});
describe("broadcast cues", () => {
  it("uses inclusive start, exclusive end and priority then recency", () => {
    const cues = [
      cue(),
      cue({ cue_id: "new", clock_ms: 2000 }),
      cue({ cue_id: "important", priority: 90 }),
    ];
    expect(activeCues(cues, 999)).toEqual([]);
    expect(activeCues(cues, 1000).map((c) => c.cue_id)).toEqual([
      "important",
      "cue1",
    ]);
    expect(activeCues(cues, 2000).map((c) => c.cue_id)).toEqual([
      "important",
      "new",
      "cue1",
    ]);
    expect(activeCues(cues, 5000).map((c) => c.cue_id)).toEqual(["new"]);
    expect(activeCues(cues, 6000)).toEqual([]);
  });
  it("renders different content and metrics for the same moment in two personas", () => {
    const common = {
      clock: 2000,
      events: [],
      safe: true,
      running: true,
      status: "live",
    };
    render(
      <>
        <ViewPanel
          {...common}
          title="ANALYST"
          persona="analyst"
          cues={[cue()]}
        />
        <ViewPanel
          {...common}
          title="FAN"
          persona="casual"
          cues={[
            cue({
              cue_id: "fan",
              persona: "casual",
              language: "es",
              payload: {
                headline: "Favorito: Cámara del jugador",
                detail: "Sigue la emoción del partido.",
                player_cam: { player_id: "match_7_H09" },
              },
            }),
          ]}
        />
      </>,
    );
    expect(
      screen.getByRole("region", { name: "ANALYST view" }),
    ).toHaveTextContent("Pressure rising");
    expect(screen.getByRole("region", { name: "FAN view" })).toHaveTextContent(
      "Sigue la emoción",
    );
    expect(screen.getAllByText("Dominance")).toHaveLength(1);
    expect(screen.getByText(/Okafor · favourite player/)).toBeInTheDocument();
  });
  it("shows before/after win probabilities and delta", () => {
    render(
      <CueCard
        cue={cue({
          template: "what_if",
          payload: {
            headline: "A different future",
            detail: "If saved",
            metrics: { win_prob_before: 0.3, win_prob_after: 0.6, delta: 0.3 },
          },
        })}
      />,
    );
    expect(screen.getByText("+30.0 pp")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });
  it("compares the actual win chance with the alternative outcome", () => {
    render(
      <CueCard
        cue={cue({
          template: "what_if",
          language: "es",
          payload: {
            headline: "What if?",
            detail: "If saved",
            metrics: {
              win_prob_before: 0.06,
              win_prob_after: 0.16,
              win_prob_counterfactual: 0.06,
              delta: 0.1,
            },
          },
        })}
      />,
    );
    expect(
      screen.getByRole("img", { name: "Lo que pasó 16%, Alternativa 6%" }),
    ).toBeInTheDocument();
    expect(screen.getByText("+10 pts")).toBeInTheDocument();
  });
  it("highlights the What-If evidence on the pitch for two match minutes", () => {
    const events: MatchEvent[] = [
      wireEvent({ sequence: 1, start_position: { x: 40, y: 30 } }),
      wireEvent({
        sequence: 2,
        event_type: "tracking_frame",
        ball_position: { x: 1, y: 1 },
      }),
      wireEvent({
        sequence: 3,
        event_type: "shot",
        position: { x: 95, y: 34 },
      }),
    ].flatMap((raw) => {
      const message = parseStreamMessage(JSON.stringify(raw));
      return message.kind === "event" ? [message.event] : [];
    });
    const props = {
      title: "For you",
      persona: "casual",
      events,
      safe: false,
      running: true,
      status: "live",
      cues: [
        cue({
          template: "what_if",
          clock_ms: 0,
          evidence_event_ids: ["e1", "e2", "e3"],
          payload: { headline: "What if?", metrics: {} },
        }),
      ],
    };
    const { rerender } = render(<ViewPanel {...props} clock={120000} />);
    expect(screen.getByTestId("pitch")).toHaveAttribute(
      "data-trail",
      JSON.stringify([
        { x: 40, y: 30 },
        { x: 95, y: 34 },
      ]),
    );
    rerender(<ViewPanel {...props} clock={120001} />);
    expect(screen.getByTestId("pitch")).toHaveAttribute("data-trail", "[]");
  });
  it("retains the latest What-If after its on-air duration without showing future results", () => {
    const props = {
      title: "For you",
      persona: "casual",
      events: [],
      safe: false,
      running: true,
      status: "live",
    };
    const { rerender } = render(
      <ViewPanel
        {...props}
        clock={10000}
        cues={[
          cue({
            template: "what_if",
            payload: {
              headline: "Retained result",
              detail: "Saved shot",
              metrics: {
                win_prob_before: 0.3,
                win_prob_after: 0.6,
                delta: 0.3,
              },
            },
          }),
          cue({
            cue_id: "future",
            clock_ms: 20000,
            template: "what_if",
            payload: { headline: "Future result" },
          }),
        ]}
      />,
    );
    expect(screen.getByText("Retained result")).toBeInTheDocument();
    expect(screen.queryByText("Future result")).not.toBeInTheDocument();
    rerender(<ViewPanel {...props} clock={0} cues={[]} />);
    expect(screen.queryByText("Retained result")).not.toBeInTheDocument();
  });
  it("updates trace, latency and recovery status, and dispatches kill", () => {
    const kill = vi.fn();
    const { rerender } = render(
      <TracePanel traces={[trace()]} onKill={kill} disabled={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Stop Tactics/ }));
    expect(kill).toHaveBeenCalledOnce();
    for (const [action, status] of [
      ["agent_down", "Recovering"],
      ["fallback_on", "Recovering"],
      ["restarted_from_checkpoint", "Recovering"],
      ["caught_up", "Running"],
    ]) {
      rerender(
        <TracePanel
          traces={[
            trace({ action, status: action === "agent_down" ? "error" : "ok" }),
          ]}
          onKill={kill}
          disabled={false}
        />,
      );
      expect(screen.getAllByText(status)[0]).toBeInTheDocument();
      expect(screen.getByRole("log")).toHaveTextContent(
        action.replaceAll("_", " "),
      );
      expect(screen.getByRole("log")).toHaveTextContent("12.3");
    }
  });
  it("keeps fallback visible after rejected output and across audience feeds", () => {
    render(
      <TracePanel
        traces={[
          trace({ action: "fallback_on", status: "fallback" }),
          trace({ action: "insight", status: "rejected" }),
          trace({ view: "casual", action: "insight", status: "ok" }),
        ]}
        onKill={() => {}}
        disabled={false}
      />,
    );
    expect(screen.getByText("Fallback")).toBeInTheDocument();
  });
});
class MockSource {
  static instances: MockSource[] = [];
  onopen?: () => void;
  onmessage?: (message: { data: string }) => void;
  onerror?: () => void;
  close = vi.fn();
  constructor(public url: string) {
    MockSource.instances.push(this);
  }
  send(message: object) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}
function Probe() {
  const s = usePlaymakersStream({
    seed: 7,
    speed: 10,
    persona: "analyst",
    language: "en",
  });
  return (
    <div>
      {s.status} events:{s.events.length} cues:{s.cues.length} traces:
      {s.traces.length}
    </div>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  MockSource.instances = [];
});
it("reconnects with backoff, deduplicates replay, and closes on unmount", () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", MockSource);
  const { unmount } = render(<Probe />);
  const source = MockSource.instances[0];
  expect(source.url).toContain(
    "/playmakers/sse?seed=7&speed=10&persona=analyst&language=en",
  );
  act(() => {
    source.onopen?.();
    source.send(wireEvent({ event_type: "pass", sequence: 0, clock_ms: 0 }));
    source.send({ type: "cue", ...cue() });
    source.send({ type: "trace", ...trace() });
    vi.advanceTimersByTime(75);
  });
  expect(screen.getByText("live events:1 cues:1 traces:1")).toBeInTheDocument();
  act(() => {
    source.onerror?.();
    vi.advanceTimersByTime(1000);
  });
  const reconnect = MockSource.instances[1];
  act(() => {
    reconnect.onopen?.();
    reconnect.send(wireEvent({ sequence: 0 }));
    reconnect.send({ type: "cue", ...cue() });
    reconnect.send({ type: "trace", ...trace() });
    reconnect.send(wireEvent({ sequence: 1 }));
    vi.advanceTimersByTime(75);
  });
  expect(screen.getByText("live events:2 cues:1 traces:1")).toBeInTheDocument();
  unmount();
  expect(reconnect.close).toHaveBeenCalledOnce();
});

it("batches bursts, bounds history, and cancels pending flushes on unmount", () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", MockSource);
  const { unmount } = render(<Probe />);
  const source = MockSource.instances[0];
  act(() => {
    source.onopen?.();
    for (let i = 0; i < 3000; i++) {
      source.send(wireEvent({ sequence: i, clock_ms: i * 10000 }));
      source.send({
        type: "cue",
        ...cue({ cue_id: `cue${i}`, clock_ms: i * 10000 }),
      });
      source.send({ type: "trace", ...trace() });
    }
  });
  expect(screen.getByText("live events:0 cues:0 traces:0")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(75));
  expect(
    screen.getByText("live events:2500 cues:400 traces:2400"),
  ).toBeInTheDocument();
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
