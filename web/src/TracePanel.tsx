import { useEffect, useRef, useState } from "react";
import { agentStatus, type Trace } from "./stream";
// Tactics and Storyline write with a language model (What-If narrates with one); the rest are rules.
const MODEL_AGENTS = new Set(["tactics", "storyline", "what_if"]);
const recoveryLabels: Record<string, string> = {
  agent_down: "Down",
  fallback_on: "Template cover: captions from templates",
  restarted_from_checkpoint: "Restored from checkpoint",
  caught_up: "Caught up",
};
const recoveryOrder = Object.keys(recoveryLabels);
const agentName = (agent: string) => agent === "what_if" ? "What-If" : agent[0].toUpperCase() + agent.slice(1);
const actionLine = (t: Trace) => {
  const line = t.detail ?? ({
    computed: "Computed match metrics",
    insight: "Drafted a caption",
    templated: "Used a template caption",
    verified: "Checked the claims",
    schema_validated: "Validated the cue",
    fan_out: "Shaped the viewer feeds",
    rollouts_verified: "Ran simulations",
    recap: "Wrote the full-time recap",
    recap_verified: "Checked the recap",
  }[t.action] ?? t.action.replaceAll("_", " "));
  const prefix = `${agentName(t.agent)} `;
  const short = line.startsWith(prefix) ? line.slice(prefix.length) : line;
  return short ? short[0].toUpperCase() + short.slice(1) : "Waiting for match events";
};
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
  killRequested = false,
}: {
  traces: Trace[];
  onKill: () => void;
  disabled: boolean;
  mockModel?: boolean;
  killRequested?: boolean;
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
  // Remember lifecycle events even after the rolling trace window drops them.
  const [recoveryActions, setRecoveryActions] = useState<string[]>(() =>
    killRequested ? ["agent_down"] : [],
  );
  const incomingRecovery = traces.filter((t) => t.agent === "tactics" && recoveryOrder.includes(t.action))
    .map((t) => t.action).join(",");
  useEffect(() => {
    if (!incomingRecovery) return;
    setRecoveryActions((previous) => [...new Set([...previous, ...incomingRecovery.split(",")])]);
  }, [incomingRecovery]);
  const recoveryAction = recoveryActions[recoveryStep];
  const displayedRecovery = recoveryAction ?? (recoveryStep < 4 ? recoveryActions.at(-1) : undefined);
  useEffect(() => {
    if (!recoveryAction) return;
    const timer = setTimeout(() => setRecoveryStep((step) => step + 1), 1500);
    return () => clearTimeout(timer);
  }, [recoveryAction]);
  const [active, setActive] = useState(new Set<string>());
  const lastActions = useRef(new Map<string, string>());
  const activityTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const latestSequence = Math.max(-1, ...traces.map((t) => t.sequence));
  const activity = JSON.stringify(agents.map((agent) => {
    const t = latest.get(agent);
    return [agent, t ? actionLine(t) : "", t?.sequence === latestSequence];
  }));
  useEffect(() => {
    const rows: [string, string, boolean][] = JSON.parse(activity);
    const changed = rows.filter(([agent, line, current]) =>
      current && line && lastActions.current.get(agent) !== line,
    ).map(([agent]) => agent);
    for (const [agent, line] of rows) lastActions.current.set(agent, line);
    if (!changed.length) return;
    // Writers, verification and simulations explain the latest cue most clearly.
    const priority = ["tactics", "compliance", "what_if", "storyline", "stats", "graphics", "audience", "director"];
    setActive(new Set(priority.filter((agent) => changed.includes(agent)).slice(0, 3)));
    clearTimeout(activityTimer.current);
    activityTimer.current = setTimeout(() => setActive(new Set()), 1500);
  }, [activity]);
  useEffect(() => () => clearTimeout(activityTimer.current), []);
  const timing = (t: Trace, agent: string) =>
    mockModel && MODEL_AGENTS.has(agent) ? "" :
      t.latency_ms >= 1 ? `${Math.round(t.latency_ms)} ms` : "";
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
          <span>2 AI agents + 6 rule-based steps</span>
          {mockModel && <small className="model-mode">Offline mock model</small>}
        </span>
      </div>
      <div className="agent-grid">
        {agents.map((agent) => {
          const t = latest.get(agent);
          const recovery = agent === "tactics" && displayedRecovery;
          const abnormal = t && agentStatus(t) !== "up" && agent !== "director";
          const line = recovery ? recoveryLabels[displayedRecovery!] :
            t ? actionLine(t) : "Waiting for match events";
          const latency = t && !recovery && agent !== "director" ? timing(t, agent) : "";
          return (
            <div key={agent} className={active.has(agent) ? "agent-active" : ""}>
              <div>
                <span>{agentName(agent)}</span>
                <small className={recovery ? `recovering ${displayedRecovery === "agent_down" ? "down" : ""}` : abnormal ? agentStatus(t!) : ""}>
                  {line}{latency ? ` · ${latency}` : ""}
                </small>
              </div>
            </div>
          );
        })}
      </div>
      <button className="kill" onClick={() => {
        setRecoveryStep(0);
        setRecoveryActions(["agent_down"]);
        onKill();
      }} disabled={disabled || Boolean(displayedRecovery)}>
        Stop Tactics agent
      </button>
      <small className="kill-note">
        Stop Tactics to watch the crew cover and recover.
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
