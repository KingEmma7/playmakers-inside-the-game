import { act, render, renderHook, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activeCues,
  usePlaymakersStream,
  type OverlayCue,
  type Trace,
} from "./stream";
import { CueCard, ViewPanel } from "./Overlay";
import { whatIfQuestion } from "./whatifCopy";
import { RecapCard } from "./Recap";
import { ProvenancePanel } from "./Provenance";
import TracePanel from "./TracePanel";
import offlineRecoveryRows from "./test-fixtures/offline-recovery.json";
import { parseStreamMessage } from "./parse";
import type { MatchEvent } from "./stream";
const offlineRecovery: Trace[] = offlineRecoveryRows.map((row) => {
  const parsed = parseStreamMessage(JSON.stringify({ type: "trace", ...row }));
  if (parsed.kind !== "trace") throw new Error("Invalid offline recovery fixture");
  return { ...parsed.trace, sequence: row.sequence, view: row.view };
});
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
  it.each(["analyst", "casual"])(
    "holds a goal through routine captions in the %s feed",
    (persona) => {
      const goal = cue({
        cue_id: "goal",
        clock_ms: 1000,
        priority: 85,
        payload: {
          headline: "GOAL, Marin 2'",
          detail: "Northbridge Rovers lead 1-0.",
          moment: "goal",
          hold_ms: 60000,
        },
      });
      const routine = cue({
        cue_id: "pass",
        clock_ms: 58000,
        payload: { headline: "Routine pass", detail: "A pass." },
      });
      const props = {
        title: "Feed",
        persona,
        events: [],
        safe: false,
        running: true,
        status: "live",
      };
      const { rerender } = render(
        <ViewPanel {...props} clock={60999} cues={[goal, routine]} />,
      );
      expect(
        screen.getByRole("heading", { name: "GOAL, Marin 2'" }),
      ).toBeInTheDocument();
      expect(screen.queryByText("Routine pass")).not.toBeInTheDocument();
      rerender(<ViewPanel {...props} clock={61000} cues={[goal, routine]} />);
      expect(
        screen.getByRole("heading", { name: "Routine pass" }),
      ).toBeInTheDocument();
      const red = cue({
        cue_id: "red",
        clock_ms: 40000,
        priority: 85,
        payload: {
          headline: "RED CARD, Keita 3'",
          moment: "card",
          hold_ms: 60000,
        },
      });
      rerender(
        <ViewPanel {...props} clock={58000} cues={[goal, routine, red]} />,
      );
      expect(
        screen.getByRole("heading", { name: "RED CARD, Keita 3'" }),
      ).toBeInTheDocument();
    },
  );
  it.each([
    [
      "en",
      "If Marin's 2' shot had been saved: win chance 41% instead of 65%.",
    ],
    [
      "es",
      "Si el disparo de Marin en el 2' hubiera sido detenido: probabilidad de victoria 41% en vez de 65%.",
    ],
    [
      "fr",
      "Si le tir de Marin à la 2' avait été arrêté : chances de victoire 41% au lieu de 65%.",
    ],
  ])("names the What-If moment and odds in %s", (language, expected) => {
    expect(
      whatIfQuestion(
        cue({
          language: language as OverlayCue["language"],
          template: "what_if",
          payload: {
            scenario: "if the shot had been saved",
            moment: { player_id: "match_38_H10", minute: 2 },
            win_team_id: "match_38_HOME",
            metrics: { win_prob_after: 0.65, win_prob_counterfactual: 0.41 },
          },
        }),
      ),
    ).toBe(expected);
  });
  it("shows goal-threat levels in analyst view and hides fan What-If", () => {
    const props = { title: "Analyst", persona: "analyst", events: [], safe: false,
      running: true, status: "live", clock: 1000 };
    const threatCue = cue({ goal_threat: [{team_id: "match_7_HOME", probability: .08,
      level: "High", horizon_ms: 300000, features: {}, evidence: {event_ids: ["e1"]}}] });
    const whatif = cue({ cue_id: "whatif", template: "what_if", payload: {headline: "Alternative result"} });
    const { rerender } = render(<ViewPanel {...props} cues={[threatCue, whatif]} />);
    expect(screen.getByLabelText("Goal threat")).toHaveTextContent("Goal threat: High, Northbridge");
    expect(screen.getByText("Alternative result")).toBeInTheDocument();
    rerender(<ViewPanel {...props} persona="casual" cues={[threatCue, whatif]} />);
    expect(screen.queryByLabelText("Goal threat")).not.toBeInTheDocument();
    expect(screen.queryByText("Alternative result")).not.toBeInTheDocument();
  });
  it("updates the persistent What-If panel when a later simulation arrives", () => {
    const first = cue({
      cue_id: "first",
      template: "what_if",
      clock_ms: 1000,
      payload: {
        headline: "What if?",
        scenario: "if the shot had been saved",
        moment: { player_id: "match_38_H10", minute: 2 },
        win_team_id: "match_38_HOME",
        metrics: { win_prob_after: 0.65, win_prob_counterfactual: 0.41 },
      },
    });
    const next = cue({
      cue_id: "next",
      template: "what_if",
      clock_ms: 900000,
      payload: {
        headline: "What if?",
        scenario: "if the chance had been scored",
        moment: { player_id: "match_38_H09", minute: 16 },
        win_team_id: "match_38_HOME",
        metrics: { win_prob_after: 0.7, win_prob_counterfactual: 0.9 },
      },
    });
    const props = {
      title: "Analyst",
      persona: "analyst",
      events: [],
      safe: false,
      running: true,
      status: "live",
      cues: [first, next],
    };
    const { rerender } = render(<ViewPanel {...props} clock={899999} />);
    expect(screen.getByText(/If Marin's 2' shot/)).toBeInTheDocument();
    rerender(<ViewPanel {...props} clock={1000000} />);
    expect(screen.queryByText(/If Marin's/)).not.toBeInTheDocument();
    expect(
      screen.getByText(
        /If Okafor's 16' chance had been scored.*90% instead of 70%/,
      ),
    ).toBeInTheDocument();
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
      title: "Analyst",
      persona: "analyst",
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
      title: "Analyst",
      persona: "analyst",
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
  it.each(["analyst", "casual"] as const)(
    "keeps all five recap goals and full player names for %s",
    (persona) => {
      const onFocus = vi.fn();
      const moments = [2, 15, 20, 62, 71].map((minute, i) => ({
        clock_ms: (minute - 1) * 60000,
        event_id: `goal-${i}`,
        kind: "goal",
        team_id: i < 3 ? "match_382_HOME" : "match_382_AWAY",
        player_id:
          i === 1 ? "match_382_H09" : i < 3 ? "match_382_H07" : "match_382_A13",
      }));
      render(
        <RecapCard
          cue={cue({ persona, template: "recap", payload: { moments } })}
          onFocus={onFocus}
          onExplain={() => {}}
        />,
      );
      expect(screen.getAllByRole("listitem")).toHaveLength(5);
      expect(
        screen.getByRole("button", { name: /15' Goal.*Okafor/ }),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /71' Goal/ }));
      expect(onFocus).toHaveBeenCalledWith("goal-4");
    },
  );
  it("starts recovery history with key events and can reveal other steps", () => {
    const actions = [
      "agent_down",
      "fallback_on",
      "restarted_from_checkpoint",
      "caught_up",
    ];
    const { container } = render(
      <TracePanel
        traces={[
          trace({ action: "handoff" }),
          ...["analyst", "casual"].flatMap((view) =>
            actions.map((action) => trace({ view, action })),
          ),
        ]}
        onKill={() => {}}
        disabled={false}
      />,
    );
    expect(container.querySelectorAll(".trace-row")).toHaveLength(8);
    for (const view of ["A", "F"]) {
      for (const action of actions) {
        expect(
          [...container.querySelectorAll(".trace-row")].some(
            (row) =>
              row.textContent?.includes(action.replaceAll("_", " ")) &&
              row.querySelector("b span")?.textContent === view,
          ),
        ).toBe(true);
      }
    }
    fireEvent.click(screen.getByRole("button", { name: "Show all steps" }));
    expect(container.querySelectorAll(".trace-row")).toHaveLength(9);
    fireEvent.click(screen.getByRole("button", { name: "Show key events" }));
    expect(container.querySelectorAll(".trace-row")).toHaveLength(8);
  });
  it("holds each real recovery step for 1.5 seconds, including batched traces", () => {
    vi.useFakeTimers();
    const kill = vi.fn();
    const { rerender, container, unmount } = render(
      <TracePanel traces={[trace()]} onKill={kill} disabled={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Stop Tactics/ }));
    expect(kill).toHaveBeenCalledOnce();
    expect(container.querySelector(".agent-grid > div:nth-child(3) .down")).toHaveTextContent("Down");
    expect(screen.getByRole("button", { name: /Stop Tactics/ })).toBeDisabled();
    const actions = ["agent_down", "fallback_on", "restarted_from_checkpoint", "caught_up"];
    const labels = ["Down", "Template cover: captions from templates", "Restored from checkpoint", "Caught up"];
    const traces = ["analyst", "casual"].flatMap((view) =>
      actions.map((action) => trace({ action, view, latency_ms: 0.1 })),
    );
    rerender(<TracePanel traces={traces} onKill={kill} disabled={false} />);
    for (const label of labels) {
      const row = container.querySelector(".agent-grid > div:nth-child(3)")!;
      expect(row).toHaveTextContent(label);
      expect(row.querySelector(".recovering")).not.toBeNull();
      act(() => vi.advanceTimersByTime(1499));
      expect(row).toHaveTextContent(label);
      act(() => vi.advanceTimersByTime(1));
    }
    expect(container.querySelector(".agent-grid .recovering")).toBeNull();
    expect(screen.getByRole("button", { name: /Stop Tactics/ })).toBeEnabled();
    expect(screen.getByRole("log")).not.toHaveTextContent("0.1");
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("displays restoration and catch-up in the real offline trace order, then allows another stop", () => {
    vi.useFakeTimers();
    // Captured from Director with the offline client, default key-moment policy,
    // four passing events and kill=tactics@20. Rejected insight follows fallback;
    // restoration and catch-up precede the routine template on the next event.
    const props = { onKill: vi.fn(), disabled: false, mockModel: true };
    const { container, rerender, unmount } = render(
      <TracePanel {...props} traces={offlineRecovery.filter((t) => t.sequence === 1)} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Stop Tactics/ }));
    const row = () => container.querySelector(".agent-grid > div:nth-child(3)")!;
    expect(row()).toHaveTextContent("Down");
    // App replaces the session on click. The optimistic state survives its new key.
    rerender(<TracePanel {...props} key="stopped" killRequested traces={[]} />);
    expect(row()).toHaveTextContent("Down");
    const failed = offlineRecovery.filter((t) => t.sequence <= 2);
    rerender(<TracePanel {...props} key="stopped" killRequested traces={failed} />);
    act(() => vi.advanceTimersByTime(1499));
    expect(row()).toHaveTextContent("Down");
    act(() => vi.advanceTimersByTime(1));
    expect(row()).toHaveTextContent("Template cover: captions from templates");
    act(() => vi.advanceTimersByTime(3000));
    expect(row()).toHaveTextContent("Template cover: captions from templates");
    expect(screen.getByRole("button", { name: /Stop Tactics/ })).toBeDisabled();
    const restored = offlineRecovery.filter((t) => t.sequence <= 3);
    rerender(<TracePanel {...props} key="stopped" killRequested traces={[
      ...restored, ...restored.map((t) => ({ ...t, view: "casual" })),
    ]} />);
    expect(row()).toHaveTextContent("Restored from checkpoint");
    // Incoming routine work and trace eviction must not erase queued lifecycle steps.
    rerender(<TracePanel {...props} key="stopped" killRequested traces={offlineRecovery.filter((t) => t.sequence === 4)} />);
    act(() => vi.advanceTimersByTime(1499));
    expect(row()).toHaveTextContent("Restored from checkpoint");
    act(() => vi.advanceTimersByTime(1));
    expect(row()).toHaveTextContent("Caught up");
    expect(row().querySelector(".recovering")).not.toBeNull();
    act(() => vi.advanceTimersByTime(1499));
    expect(row()).toHaveTextContent("Caught up");
    act(() => vi.advanceTimersByTime(1));
    expect(row()).toHaveTextContent("Routine play: rule-written caption");
    expect(row().querySelector(".recovering")).toBeNull();
    expect(screen.getByRole("button", { name: /Stop Tactics/ })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Stop Tactics/ }));
    expect(row()).toHaveTextContent("Down");
    expect(props.onKill).toHaveBeenCalledTimes(2);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(["tactics", "storyline"])("distinguishes routine writing from model writing for %s", (agent) => {
    const { container, rerender } = render(
      <TracePanel traces={[trace({ agent, action: "templated", detail: `${agent} used a template caption` })]} onKill={() => {}} disabled={false} mockModel />,
    );
    expect(screen.getByText("Routine play: rule-written caption")).toBeInTheDocument();
    expect(container.querySelector(".recovering")).toBeNull();
    rerender(<TracePanel traces={[trace({ agent, action: "insight", detail: `${agent} drafted a caption` })]} onKill={() => {}} disabled={false} mockModel />);
    expect(screen.getByText("Wrote the caption")).toBeInTheDocument();
    expect(screen.queryByText("Routine play: rule-written caption")).not.toBeInTheDocument();
  });
  it("briefly tints agents that produced a trace and renders its actual detail", () => {
    vi.useFakeTimers();
    const traces = [trace({ agent: "compliance", detail: "Compliance checked 3 numbers", latency_ms: 0.1 })];
    const { container, rerender } = render(<TracePanel traces={traces} onKill={() => {}} disabled={false} />);
    expect(screen.getByText("Checked 3 numbers")).toBeInTheDocument();
    expect(container.querySelector(".agent-grid > div:nth-child(5)")).toHaveClass("agent-active");
    act(() => vi.advanceTimersByTime(1500));
    expect(container.querySelector(".agent-active")).toBeNull();
    rerender(<TracePanel traces={[...traces]} onKill={() => {}} disabled={false} />);
    expect(container.querySelector(".agent-active")).toBeNull();
  });
  it("tints only changed action lines for the latest cue, at most three at once", () => {
    vi.useFakeTimers();
    const crew = ["director", "stats", "tactics", "storyline", "compliance", "graphics", "audience", "what_if"];
    const original = crew.map((agent) => trace({ agent, detail: `${agent} completed work` }));
    const { container, rerender, unmount } = render(<TracePanel traces={original} onKill={() => {}} disabled={false} />);
    expect(container.querySelectorAll(".agent-active")).toHaveLength(3);
    act(() => vi.advanceTimersByTime(1500));
    const repeated = original.map((t) => ({ ...t, sequence: 2, latency_ms: 50 }));
    rerender(<TracePanel traces={[...original, ...repeated]} onKill={() => {}} disabled={false} />);
    expect(container.querySelectorAll(".agent-active")).toHaveLength(0);
    const changed = repeated.map((t) => ({
      ...t, sequence: 3,
      detail: t.agent === "compliance" ? "Compliance checked 20 numbers" : t.detail,
    }));
    rerender(<TracePanel traces={changed} onKill={() => {}} disabled={false} />);
    expect(container.querySelectorAll(".agent-active")).toHaveLength(1);
    expect(container.querySelector(".agent-active")).toHaveTextContent("Checked 20 numbers");
    act(() => vi.advanceTimersByTime(750));
    rerender(<TracePanel traces={changed.map((t) => ({ ...t, sequence: 4 }))} onKill={() => {}} disabled={false} />);
    act(() => vi.advanceTimersByTime(750));
    expect(container.querySelector(".agent-active")).toBeNull();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("names the crew honestly and labels mock-model timings as mock", () => {
    const traces = [trace(), trace({ agent: "compliance", latency_ms: 0.4 })];
    const { rerender } = render(
      <TracePanel traces={traces} onKill={() => {}} disabled={false} />,
    );
    expect(
      screen.getByText("2 AI agents + 6 rule-based steps"),
    ).toBeInTheDocument();
    expect(screen.getByText("Wrote the caption · 12 ms")).toBeInTheDocument();
    rerender(
      <TracePanel
        traces={traces}
        onKill={() => {}}
        disabled={false}
        mockModel
      />,
    );
    expect(
      screen.getByText("Offline mock model"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Wrote the caption · 12 ms")).not.toBeInTheDocument();
    expect(screen.getByText("Wrote the caption")).toBeInTheDocument();
    expect(screen.queryByText(/0.4 ms/)).not.toBeInTheDocument();
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
    expect(screen.getByLabelText("Match metrics")).toHaveTextContent(
      "75%Possession",
    );
    expect(screen.getByLabelText("Match metrics")).toHaveTextContent(
      "75%Field tilt",
    );
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
    expect(screen.getByText("Template cover: captions from templates")).toBeInTheDocument();
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


it("receives all fan languages in one stream with recap, What-If and trace history", () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", MockSource);
  const { result, rerender } = renderHook(() => usePlaymakersStream({
    seed: 7, speed: 10, session_id: "same-match", persona: "casual", language: "en", all_languages: true,
  }));
  const first = MockSource.instances[0];
  expect(first.url).toContain("all_languages=true");
  act(() => {
    first.send(wireEvent({ sequence: 42, clock_ms: 123000 }));
    for (const language of ["en", "es", "fr"] as const) {
      first.send({ type: "cue", ...cue({ cue_id: `recap-${language}`, template: "recap", language }) });
      first.send({ type: "cue", ...cue({ cue_id: `whatif-${language}`, template: "what_if", language }) });
    }
    first.send({ type: "trace", ...trace() });
    vi.advanceTimersByTime(75);
  });
  const before = result.current;
  rerender();
  expect(MockSource.instances).toHaveLength(1);
  expect(result.current).toBe(before);
  expect(result.current.events.at(-1)?.clock_ms).toBe(123000);
  expect(result.current.cues).toHaveLength(6);
  expect(result.current.traces).toHaveLength(1);
});
