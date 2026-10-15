import { clockLabel, agentStatus, type Trace } from "./stream";
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
  recoveryClock = 0,
}: {
  traces: Trace[];
  onKill: () => void;
  disabled: boolean;
  recoveryClock?: number;
}) {
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
  const recovery = latest.get("tactics");
  const recoveryStatus = recovery ? agentStatus(recovery) : "waiting";
  const history = traces.filter(
    (t, index) =>
      index >= traces.length - 70 ||
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
        <span>{agents.length} specialists</span>
      </div>
      <div className="agent-grid">
        {agents.map((agent) => {
          const t =
            latest.get(agent) ??
            (agent === "director" ? traces.at(-1) : undefined);
          let status = t
            ? agent === "director"
              ? "up"
              : agentStatus(t)
            : "waiting";
          if (agent === "tactics" && ["down", "fallback"].includes(status))
            status = "recovering";
          if (
            agent === "graphics" &&
            ["down", "fallback", "recovering"].includes(recoveryStatus)
          )
            status = "fallback";
          return (
            <div key={agent}>
              <div>
                <span>
                  {agent === "what_if"
                    ? "What-If"
                    : agent[0].toUpperCase() + agent.slice(1)}
                </span>
                <small>
                  {agent === "tactics" && status === "recovering"
                    ? `replaying from ${clockLabel(recoveryClock)}`
                    : agent === "graphics" && status === "fallback"
                      ? "template mode"
                      : agent === "director"
                        ? "Orchestrating the gallery"
                        : t
                          ? `${t.action.replaceAll("_", " ")} · ${t.latency_ms.toFixed(1)} ms`
                          : "Waiting for match events"}
                </small>
              </div>
              <b className={`status ${status}`}>
                {
                  {
                    up: "Running",
                    recovering: "Recovering",
                    fallback: "Fallback",
                    down: "Down",
                    waiting: "Waiting",
                  }[status]
                }
              </b>
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
        <div className="trace-list" role="log" aria-label="Agent handoffs">
          {traces.length === 0 && (
            <p className="empty">Awaiting the first handoff…</p>
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
                <time>
                  {t.latency_ms.toFixed(1)}
                  <small>ms</small>
                </time>
              </div>
            ))}
        </div>
      </details>
    </aside>
  );
}
