import { act, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeCues,
  usePlaymakersStream,
  type OverlayCue,
  type Trace,
} from "./stream";
import { CueCard, ViewPanel } from "./Overlay";
import { RecapCard } from "./Recap";
import { ProvenancePanel } from "./Provenance";
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
const parseEvent = (fields: Record<string, unknown>): MatchEvent => {
  const message = parseStreamMessage(JSON.stringify(wireEvent(fields)));
  if (message.kind !== "event") throw new Error("not an event");
  return message.event;
};
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
          language="es"
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
    expect(screen.getAllByText("Dominio")).toHaveLength(1);
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
  it("explains a cue: agent, verdict, clickable evidence and stats used", () => {
    const events: MatchEvent[] = [
      wireEvent({ sequence: 1, start_position: { x: 40, y: 30 } }),
      wireEvent({
        sequence: 2,
        clock_ms: 65000,
        start_position: { x: 60, y: 20 },
      }),
    ].flatMap((raw) => {
      const message = parseStreamMessage(JSON.stringify(raw));
      return message.kind === "event" ? [message.event] : [];
    });
    render(
      <ViewPanel
        title="Analyst"
        persona="analyst"
        events={events}
        safe={false}
        running
        status="live"
        clock={70000}
        cues={[
          cue({
            clock_ms: 65000,
            evidence_event_ids: ["e1", "e2"],
            provenance: {
              agent: "tactics",
              source: "agent",
              compliance: "verified",
              attempts: 2,
              reasons: ["Ungrounded metric: difficulty"],
              metrics: { difficulty: 0.6 },
              metric_evidence: { difficulty: ["e2"] },
            },
          }),
        ]}
      />,
    );
    expect(screen.getByTestId("pitch")).toHaveAttribute("data-trail", "[]");
    fireEvent.click(screen.getByRole("button", { name: "Why?" }));
    const panel = screen.getByRole("dialog", { name: "Tactics agent: Why?" });
    expect(panel).toHaveTextContent(
      "Compliance rejected 1 draft (Ungrounded metric: difficulty), then verified the correction.",
    );
    expect(panel).toHaveTextContent("difficulty 0.60 · #2");
    expect(screen.getByTestId("pitch")).toHaveAttribute(
      "data-trail",
      JSON.stringify([
        { x: 40, y: 30 },
        { x: 60, y: 20 },
      ]),
    );
    fireEvent.click(screen.getByRole("button", { name: "#2 pass · 01:05" }));
    expect(screen.getByTestId("pitch")).toHaveAttribute(
      "data-trail",
      JSON.stringify([{ x: 60, y: 20 }]),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Pressure rising")).toBeInTheDocument();
  });
  it("does not label a template fallback as verified", () => {
    render(
      <CueCard
        cue={cue({
          template: "template_fallback",
          provenance: {
            agent: "storyline",
            source: "template",
            compliance: "template_fallback",
            reasons: ["Ungrounded number in prose"],
          },
        })}
        onExplain={() => {}}
      />,
    );
    expect(screen.getByTestId("cue-card")).not.toHaveTextContent("· Verified");
    expect(screen.getByRole("button", { name: "Why?" })).toBeInTheDocument();
  });
  it("says when a routine insight came from a rule instead of a model", () => {
    render(
      <ProvenancePanel
        cue={cue({
          provenance: {
            agent: "tactics",
            source: "template",
            compliance: "verified",
            metrics: { difficulty: 0.6 },
            metric_evidence: { difficulty: ["e1"] },
          },
        })}
        events={[]}
        onFocus={() => {}}
        onClose={() => {}}
      />,
    );
    expect(
      screen.getByRole("dialog", { name: "Tactics agent: Why?" }),
    ).toHaveTextContent(
      "A routine moment, so no model was called: a rule wrote this from verified stats, and Compliance checked every number.",
    );
  });
  it("shows the full-time recap with moments, pitch highlights and copy", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const events: MatchEvent[] = [
      wireEvent({
        sequence: 1,
        event_type: "shot",
        team_id: "match_7_HOME",
        shooter_player_id: "match_7_H09",
        position: { x: 95, y: 30 },
        xg: 0.4,
        outcome: "goal",
      }),
      wireEvent({
        sequence: 2,
        event_type: "goal",
        clock_ms: 360000,
        scoring_team_id: "match_7_HOME",
        scorer_player_id: "match_7_H09",
        shot_event_id: "e1",
      }),
    ].flatMap((raw) => {
      const message = parseStreamMessage(JSON.stringify(raw));
      return message.kind === "event" ? [message.event] : [];
    });
    render(
      <ViewPanel
        title="For you"
        persona="casual"
        events={events}
        safe={false}
        running={false}
        status="ended"
        clock={5400000}
        cues={[
          cue({
            cue_id: "ft:recap:viewer1",
            template: "recap",
            clock_ms: 5400000,
            duration_ms: 30000,
            priority: 90,
            persona: "casual",
            language: "es",
            evidence_event_ids: ["e2", "ft"],
            payload: {
              headline: "Final: Northbridge Rovers 1–0 Southport Athletic",
              detail: "¡Qué partido! Gana Northbridge Rovers.",
              moments: [
                {
                  clock_ms: 360000,
                  event_id: "e2",
                  kind: "goal",
                  team_id: "match_7_HOME",
                  player_id: "match_7_H09",
                },
                { clock_ms: 1, kind: "not-a-moment" },
              ],
            },
          }),
        ]}
      />,
    );
    const recap = screen.getByRole("region", { name: "Resumen del partido" });
    expect(recap).toHaveTextContent(
      "Final: Northbridge Rovers 1–0 Southport Athletic",
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByTestId("pitch")).toHaveAttribute(
      "data-trail",
      JSON.stringify([{ x: 95, y: 30 }]),
    );
    fireEvent.click(screen.getByRole("button", { name: "Copiar" }));
    await screen.findByText("Copiado");
    expect(writeText).toHaveBeenCalledWith(
      "Final: Northbridge Rovers 1–0 Southport Athletic\n¡Qué partido! Gana Northbridge Rovers.\n7' Gol · Northbridge Rovers (Okafor)",
    );
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
  it.each(["analyst", "casual"] as const)("keeps all five recap goals and full player names for %s", (persona) => {
    const onFocus = vi.fn();
    const moments = [2, 15, 20, 62, 71].map((minute, i) => ({
      clock_ms: (minute - 1) * 60000,
      event_id: `goal-${i}`,
      kind: "goal",
      team_id: i < 3 ? "match_382_HOME" : "match_382_AWAY",
      player_id: i === 1 ? "match_382_H09" : i < 3 ? "match_382_H07" : "match_382_A13",
    }));
    render(<RecapCard cue={cue({ persona, template: "recap", payload: { moments } })} onFocus={onFocus} onExplain={() => {}} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByRole("button", { name: /15' Goal.*Okafor/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /71' Goal/ }));
    expect(onFocus).toHaveBeenCalledWith("goal-4");
  });
  it("starts recovery history with key events and can reveal other steps", () => {
    const actions = ["agent_down", "fallback_on", "restarted_from_checkpoint", "caught_up"];
    const { container } = render(<TracePanel traces={[
      trace({ action: "handoff" }),
      ...["analyst", "casual"].flatMap((view) => actions.map((action) => trace({ view, action }))),
    ]} onKill={() => {}} disabled={false} />);
    expect(container.querySelectorAll(".trace-row")).toHaveLength(8);
    for (const view of ["A", "F"]) {
      for (const action of actions) {
        expect([...container.querySelectorAll(".trace-row")].some((row) =>
          row.textContent?.includes(action.replaceAll("_", " ")) && row.querySelector("b span")?.textContent === view,
        )).toBe(true);
      }
    }
    fireEvent.click(screen.getByRole("button", { name: "Show all steps" }));
    expect(container.querySelectorAll(".trace-row")).toHaveLength(9);
    fireEvent.click(screen.getByRole("button", { name: "Show key events" }));
    expect(container.querySelectorAll(".trace-row")).toHaveLength(8);
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
  it("names the crew honestly and labels mock-model timings as mock", () => {
    const traces = [trace(), trace({ agent: "compliance", latency_ms: 0.4 })];
    const { rerender } = render(
      <TracePanel traces={traces} onKill={() => {}} disabled={false} />,
    );
    expect(screen.getByText("2 AI agents + 6 rule-based steps")).toBeInTheDocument();
    expect(screen.getByText("insight · 12.3 ms")).toBeInTheDocument();
    rerender(
      <TracePanel traces={traces} onKill={() => {}} disabled={false} mockModel />,
    );
    expect(screen.getByText("insight · offline mock model")).toBeInTheDocument();
    expect(screen.queryByText("insight · 12.3 ms")).not.toBeInTheDocument();
    expect(screen.getByText("insight · 0.4 ms")).toBeInTheDocument();
  });
  it("waits for enough events before showing possession and field tilt", () => {
    const passes = (count: number, team: string, x: number) =>
      Array.from({ length: count }, (_, i) =>
        parseEvent({
          sequence: i,
          event_type: "pass",
          team_id: team,
          end_position: { x, y: 34 },
          difficulty: 0.2,
        }),
      );
    const props = {
      title: "Analyst",
      persona: "analyst",
      cues: [],
      clock: 0,
      safe: false,
      running: true,
      status: "",
    };
    const early = passes(3, "match_7_HOME", 80);
    const { rerender } = render(
      <ViewPanel {...props} events={early} event={early.at(-1)} />,
    );
    const metrics = screen.getByLabelText("Match metrics");
    expect(metrics).toHaveTextContent("—Possession");
    expect(metrics).toHaveTextContent("—Field tilt");
    expect(metrics).not.toHaveTextContent("100%");
    const settled = [
      ...passes(30, "match_7_HOME", 80),
      ...passes(10, "match_7_AWAY", 20),
    ].map((e, i) => ({ ...e, sequence: i }));
    rerender(<ViewPanel {...props} events={settled} event={settled.at(-1)} />);
    expect(screen.getByLabelText("Match metrics")).toHaveTextContent("75%Possession");
    expect(screen.getByLabelText("Match metrics")).toHaveTextContent("75%Field tilt");
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

function OfflineProbe() {
  const s = usePlaymakersStream({
    seed: 7,
    speed: 10,
    persona: "casual",
    language: "es",
  });
  return <div>offline:{s.offline ?? "no"}</div>;
}
it("records when the API fell back to the offline crew", () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", MockSource);
  render(<OfflineProbe />);
  const source = MockSource.instances[0];
  expect(screen.getByText("offline:no")).toBeInTheDocument();
  act(() => {
    source.onopen?.();
    source.send({ type: "status", model: "offline", reason: "busy" });
  });
  expect(screen.getByText("offline:busy")).toBeInTheDocument();
});
