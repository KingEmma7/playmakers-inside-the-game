import { act, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeCues,
  useGalleryStream,
  type OverlayCue,
  type Trace,
} from "./stream";
import { CueCard, ViewPanel } from "./Overlay";
import TracePanel from "./TracePanel";
vi.mock("./Pitch", () => ({ default: () => <div data-testid="pitch" /> }));
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
                headline: "★ Cámara del jugador",
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
    expect(screen.getAllByText("CONTROL / MOMENTUM")).toHaveLength(1);
    expect(screen.getByText(/H09 · favourite player/)).toBeInTheDocument();
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
  it("updates trace, latency and recovery status, and dispatches kill", () => {
    const kill = vi.fn();
    const { rerender } = render(
      <TracePanel traces={[trace()]} onKill={kill} disabled={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Kill Tactics/ }));
    expect(kill).toHaveBeenCalledOnce();
    for (const [action, status] of [
      ["agent_down", "down"],
      ["fallback_on", "fallback"],
      ["restarted_from_checkpoint", "recovering"],
      ["caught_up", "up"],
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
      expect(screen.getByText(status)).toBeInTheDocument();
      expect(screen.getByRole("log")).toHaveTextContent(
        action.replaceAll("_", " "),
      );
      expect(screen.getByRole("log")).toHaveTextContent("12.3");
    }
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
  const s = useGalleryStream({
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
    "/gallery/sse?seed=7&speed=10&persona=analyst&language=en",
  );
  act(() => {
    source.onopen?.();
    source.send({
      type: "event",
      event_type: "pass",
      sequence: 0,
      clock_ms: 0,
    });
    source.send({ type: "cue", ...cue() });
    source.send({ type: "trace", ...trace() });
  });
  expect(screen.getByText("live events:1 cues:1 traces:1")).toBeInTheDocument();
  act(() => {
    source.onerror?.();
    vi.advanceTimersByTime(1000);
  });
  const reconnect = MockSource.instances[1];
  act(() => {
    reconnect.onopen?.();
    reconnect.send({ type: "event", sequence: 0 });
    reconnect.send({ type: "cue", ...cue() });
    reconnect.send({ type: "trace", ...trace() });
    reconnect.send({ type: "event", sequence: 1 });
  });
  expect(screen.getByText("live events:2 cues:1 traces:1")).toBeInTheDocument();
  unmount();
  expect(reconnect.close).toHaveBeenCalledOnce();
});
