import { agentStatus, type Trace } from "./stream";
const agents = [
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
}: {
  traces: Trace[];
  onKill: () => void;
  disabled: boolean;
}) {
  const latest = new Map<string, Trace>();
  for (const trace of traces) latest.set(trace.agent, trace);
  return (
    <aside className="trace-panel">
      <div className="rail-heading">
        <span className="eyebrow">THE GALLERY FLOOR</span>
        <h2>
          Agent trace <span>{traces.length}</span>
        </h2>
        <p>Handoffs, evidence, recovery. Live.</p>
      </div>
      <div className="agent-grid">
        {agents.map((agent) => {
          const t = latest.get(agent);
          const status = t ? agentStatus(t) : "waiting";
          return (
            <div key={agent}>
              <span>{agent.replace("_", "-")}</span>
              <b className={`status ${status}`}>{status}</b>
            </div>
          );
        })}
      </div>
      <button className="kill" onClick={onKill} disabled={disabled}>
        ⏻ Kill Tactics agent
      </button>
      <small className="kill-note">
        Replay both feeds with failure at the current minute.
      </small>
      <div className="trace-list" role="log" aria-label="Agent handoffs">
        {traces.length === 0 && (
          <p className="empty">Awaiting the first handoff…</p>
        )}
        {traces
          .slice(-70)
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
    </aside>
  );
}
