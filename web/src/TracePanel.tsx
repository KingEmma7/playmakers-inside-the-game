import { useEffect, useRef, useState } from "react";
import { agentStatus, type Trace } from "./stream";
// Tactics and Storyline write with a language model (What-If narrates with one); the rest are rules.
const MODEL_AGENTS = new Set(["tactics", "storyline", "what_if"]);
const agents = [
  "director",
  "stats",
  "tactics",
  "storyline",
  "compliance",
  "graphics",
  "audience",
  "what_if",
];
export default function TracePanel({
  traces,
  onKill,
  disabled,
  mockModel = false,
}: {
  traces: Trace[];
  onKill: () => void;
  disabled: boolean;
  mockModel?: boolean;
}) {
  const [showAll, setShowAll] = useState(false);
  const latest = new Map<string, Trace>();
  const byView = new Map<string, Trace>();
  for (const trace of traces) {
    const key = `${trace.agent}:${trace.view}`;
    if (trace.status === "rejected" && byView.has(key)) continue;
    byView.set(key, trace);
  }
  const severity: Record<string, number> = {
    up: 0,
    waiting: 1,
    recovering: 2,
    fallback: 3,
    down: 4,
  };
  for (const trace of byView.values()) {
    const previous = latest.get(trace.agent);
    if (
      !previous ||
      severity[agentStatus(trace)] >= severity[agentStatus(previous)]
    )
      latest.set(trace.agent, trace);
  }
  const [recoveryStep, setRecoveryStep] = useState(0);
  const recoveryActions = [...new Set(traces.filter((t) =>
    t.agent === "tactics" && ["agent_down", "fallback_on", "restarted_from_checkpoint", "caught_up"].includes(t.action),
  ).map((t) => t.action))];
  const recoveryAction = recoveryActions[recoveryStep];
  useEffect(() => {
    if (!recoveryAction) return;
    const timer = setTimeout(() => setRecoveryStep((step) => step + 1), 1500);
    return () => clearTimeout(timer);
  }, [recoveryAction]);
  const [active, setActive] = useState(new Set<string>());
  const lastActions = useRef(new Map<string, Trace>());
  const activityTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  useEffect(() => {
    const changed: string[] = [];
    const newest = new Map(traces.map((trace) => [trace.agent, trace]));
    for (const trace of newest.values()) {
      if (lastActions.current.get(trace.agent) === trace) continue;
      changed.push(trace.agent);
      lastActions.current.set(trace.agent, trace);
    }
    if (!changed.length) return;
    setActive((previous) => new Set([...previous, ...changed]));
    for (const agent of new Set(changed)) {
      clearTimeout(activityTimers.current.get(agent));
      activityTimers.current.set(agent, setTimeout(() => {
        setActive((previous) => { const next = new Set(previous); next.delete(agent); return next; });
      }, 1500));
    }
  }, [traces]);
  useEffect(() => {
    const timers = activityTimers.current;
    const previous = lastActions.current;
    return () => {
      for (const timer of timers.values()) clearTimeout(timer);
      previous.clear();
    };
  }, []);
  const recoveryStatus = recoveryAction ? "recovering" : "up";
  const timing = (t: Trace, agent: string) =>
    mockModel && MODEL_AGENTS.has(agent) ? "offline mock model" :
      t.latency_ms >= 1 ? `${Math.round(t.latency_ms)} ms` : "";
  const actionLine = (t: Trace, agent: string) => t.detail ?? ({
    computed: "Stats computed match metrics",
    insight: `${agent[0].toUpperCase() + agent.slice(1)} drafted a caption`,
    templated: `${agent[0].toUpperCase() + agent.slice(1)} used a template caption`,
    verified: "Compliance checked the claims",
    schema_validated: "Graphics validated the cue",
    fan_out: "Audience shaped the viewer feeds",
    rollouts_verified: "What-If ran simulations",
    recap: "Storyline wrote the full-time recap",
    recap_verified: "Compliance checked the recap",
  }[t.action] ?? t.action.replaceAll("_", " "));
  const history = traces.filter(
    (t) =>
      showAll ||
      [
        "agent_down",
        "fallback_on",
        "restarted_from_checkpoint",
        "caught_up",
      ].includes(t.action),
  );
  return (
    <aside className="trace-panel">
      <div className="rail-heading">
        <h2>Agents</h2>
        <span title="Tactics and Storyline write with a language model. Director, Stats, Compliance, Graphics and Audience are deterministic Agent Framework steps; What-If runs simulations and only its explanation uses a model.">
          2 AI agents + 6 rule-based steps
        </span>
      </div>
      <div className="agent-grid">
        {agents.map((agent) => {
          const t = latest.get(agent);
          const recoveryLabels: Record<string, string> = {
            agent_down: "Down",
            fallback_on: "Template cover: captions from templates",
            restarted_from_checkpoint: "Restored from checkpoint",
            caught_up: "Caught up",
          };
          const recovery = agent === "tactics" && recoveryAction;
          const abnormal = t && agentStatus(t) !== "up" && agent !== "director";
          const line = recovery ? recoveryLabels[recoveryAction!] :
            t ? actionLine(t, agent) : "Waiting for match events";
          const latency = t && !recovery && agent !== "director" ? timing(t, agent) : "";
          return (
            <div key={agent} className={active.has(agent) ? "agent-active" : ""}>
              <div>
                <span>{agent === "what_if" ? "What-If" : agent[0].toUpperCase() + agent.slice(1)}</span>
                <small className={recovery ? `recovering ${recoveryAction === "agent_down" ? "down" : ""}` : abnormal ? agentStatus(t!) : ""}>
                  {line}{latency ? ` · ${latency}` : ""}
                </small>
              </div>
            </div>
          );
        })}
      </div>
      <button className="kill" onClick={onKill} disabled={disabled}>
        Stop Tactics agent
      </button>
      <small className="kill-note">
        {["down", "fallback", "recovering"].includes(recoveryStatus)
          ? "Graphics uses safe templates while Tactics restores its checkpoint and catches up."
          : "Stop Tactics to see template fallback, checkpoint recovery and catch-up in both feeds."}
      </small>
      <details>
        <summary>Handoffs and recovery history</summary>
        <button
          type="button"
          className="history-toggle"
          aria-pressed={showAll}
          onClick={() => setShowAll((value) => !value)}
        >
          {showAll ? "Show key events" : "Show all steps"}
        </button>
        <div className="trace-list" role="log" aria-label="Agent handoffs">
          {history.length === 0 && (
            <p className="empty">
              {showAll ? "Awaiting the first handoff…" : "No recovery events yet."}
            </p>
          )}
          {history
            .slice()
            .reverse()
            .map((t, i) => (
              <div
                className={`trace-row ${t.status}`}
                key={`${t.view}-${t.sequence}-${t.agent}-${t.action}-${i}`}
              >
                <i />
                <div>
                  <b>
                    {t.agent} <span>{t.view === "analyst" ? "A" : "F"}</span>
                  </b>
                  <p>{t.action.replaceAll("_", " ")}</p>
                </div>
                {timing(t, t.agent) && <time>{timing(t, t.agent)}</time>}
              </div>
            ))}
        </div>
      </details>
    </aside>
  );
}
