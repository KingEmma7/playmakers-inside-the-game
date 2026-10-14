import Pitch from "./Pitch";
import {
  activeCues,
  clockLabel,
  type MatchEvent,
  type OverlayCue,
} from "./stream";
export function Crest({ away = false }: { away?: boolean }) {
  return (
    <svg width="26" height="30" viewBox="0 0 26 30" aria-hidden="true">
      <path d="M2 2H24V20L13 28 2 20Z" fill={away ? "#ffba72" : "#83d9e4"} />
      <path
        d={away ? "M7 8H19L13 21Z" : "M7 21V9L13 15 19 9V21"}
        fill="none"
        stroke="#10222d"
        strokeWidth="2.5"
      />
    </svg>
  );
}
const record = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
export function CueCard({ cue }: { cue: OverlayCue }) {
  const payload = cue.payload;
  const metrics = record(payload.metrics);
  const whatif = cue.template === "what_if";
  return (
    <article
      className={`cue ${whatif ? "whatif" : ""} ${cue.template === "template_fallback" ? "fallback" : ""}`}
      style={{ zIndex: (cue.priority ?? 0) + 1 }}
      data-testid="cue-card"
    >
      <div className="eyebrow">
        {whatif
          ? "↗ WHAT-IF LAB · HOME WIN CHANCE"
          : cue.template === "template_fallback"
            ? "RESILIENCE · SAFE TEMPLATE"
            : cue.template === "storyline"
              ? "THE STORY SO FAR"
              : "GALLERY INSIGHT"}
        <span>{cue.evidence_event_ids.length} cited events</span>
      </div>
      <h3>{String(payload.headline || cue.template)}</h3>
      <p>{String(payload.detail || "")}</p>
      {Boolean(payload.player_cam) && (
        <div className="favourite">
          ★ {String(record(payload.player_cam).player_id).split("_").at(-1)} ·
          favourite player
        </div>
      )}
      {whatif && (
        <>
          <div className="probabilities">
            <span>
              {(Number(metrics.win_prob_before) * 100).toFixed(0)}%{" "}
              <small>BEFORE</small>
            </span>
            <b>→</b>
            <span>
              {(Number(metrics.win_prob_after) * 100).toFixed(0)}%{" "}
              <small>AFTER</small>
            </span>
            <strong>
              {Number(metrics.delta) >= 0 ? "+" : ""}
              {(Number(metrics.delta) * 100).toFixed(1)} pp
            </strong>
          </div>
          <div className="delta-track">
            <i
              style={{
                width: `${Math.min(100, Math.abs(Number(metrics.delta)) * 100)}%`,
                background:
                  Number(metrics.delta) >= 0 ? "var(--lime)" : "var(--red)",
              }}
            />
          </div>
          <small>
            Seeded synthetic simulation · illustrative probabilities
          </small>
        </>
      )}
    </article>
  );
}
export function ViewPanel({
  title,
  persona,
  event,
  events,
  cues,
  clock,
  safe,
  running,
  status,
}: {
  title: string;
  persona: string;
  event?: MatchEvent;
  events: MatchEvent[];
  cues: OverlayCue[];
  clock: number;
  safe: boolean;
  running: boolean;
  status: string;
}) {
  const active = activeCues(cues, clock);
  // One winner per slot; incoming cues replace lower-priority captions instead of covering the pitch.
  const primary = active.find((c) => c.template !== "what_if");
  const whatif = active.find((c) => c.template === "what_if");
  const storyline = active.find(
    (c) =>
      c.template === "storyline" &&
      c.cue_id !== primary?.cue_id &&
      (c.payload.headline !== primary?.payload.headline ||
        c.payload.detail !== primary?.payload.detail),
  );
  const shot = events
    .filter(
      (e) =>
        e.event_type === "shot" &&
        e.sequence <= (event?.sequence ?? -1) &&
        e.clock_ms <= clock &&
        clock < e.clock_ms + 6000,
    )
    .at(-1);
  const score = events.reduce(
    (s, e) => {
      if (e.event_type === "goal" && e.sequence <= (event?.sequence ?? -1))
        s[e.scoring_team_id.endsWith("_HOME") ? 0 : 1]++;
      return s;
    },
    [0, 0],
  );
  const metrics = record(primary?.payload.metrics);
  const momentum = Number(metrics.home_momentum ?? 0);
  return (
    <section className={`view ${persona}`} aria-label={`${title} view`}>
      <div className="view-heading">
        <div>
          <span className="view-dot" />
          {title}
          <small>
            {persona === "analyst"
              ? "Tactical intelligence"
              : "Your match. Your language."}
          </small>
        </div>
        <span className="connection">{status}</span>
      </div>
      <div className="broadcast">
        <Pitch event={event} running={running} />
        <div className="vignette" />
        {safe && (
          <div className="safe-guides">
            <span>90% BROADCAST SAFE</span>
          </div>
        )}
        <div className="scorebug">
          <Crest />
          <b>NBR</b>
          <strong>
            {score[0]} <span>:</span> {score[1]}
          </strong>
          <b>SPA</b>
          <Crest away />
          <time>{clockLabel(clock)}</time>
        </div>
        <div className="on-air">
          SYNTHETIC · {event?.period === 2 ? "2ND" : "1ST"} HALF
        </div>
        {persona === "analyst" && (
          <div className="momentum">
            <div>
              <span>CONTROL / MOMENTUM</span>
              <b>{momentum > 0 ? "NBR" : momentum < 0 ? "SPA" : "EVEN"}</b>
            </div>
            <div className="meter">
              <i
                style={{
                  width: `${50 + Math.max(-1, Math.min(1, momentum)) * 50}%`,
                }}
              />
            </div>
          </div>
        )}
        {persona === "analyst" && event?.event_type === "pass" && (
          <div className="pass-stat">
            <svg viewBox="0 0 100 60">
              <path
                d="M10 50 A40 40 0 0 1 90 50"
                pathLength="100"
                fill="none"
                stroke="#ffffff20"
                strokeWidth="5"
              />
              <path
                d="M10 50 A40 40 0 0 1 90 50"
                pathLength="100"
                fill="none"
                stroke="var(--lime)"
                strokeWidth="5"
                strokeDasharray={`${event.difficulty * 100} 100`}
              />
            </svg>
            <b>{(event.difficulty * 100).toFixed(0)}%</b>
            <small>PASS DIFFICULTY</small>
          </div>
        )}
        {shot?.event_type === "shot" && (
          <div className="shot-card">
            <span>SHOT QUALITY</span>
            <b>
              {shot.xg.toFixed(2)} <small>xG</small>
            </b>
            <small>{shot.outcome.replace("_", " ")}</small>
          </div>
        )}
        <div className="lower-thirds">
          {whatif && <CueCard key={whatif.cue_id} cue={whatif} />}
          {!whatif && storyline && (
            <CueCard key={storyline.template} cue={storyline} />
          )}
          {primary && <CueCard key={primary.template} cue={primary} />}
        </div>
        {!event && (
          <div className="loading">
            Connecting to the gallery
            <span>Waiting for the synthetic match feed…</span>
          </div>
        )}
      </div>
      <div className="view-footer">
        <span>
          {persona === "analyst"
            ? "VERIFIED METRICS + TACTICS"
            : "PERSONALISED SECOND SCREEN"}
        </span>
        <span>16:9 · {safe ? "SAFE AREA ON" : "PROGRAM"}</span>
      </div>
    </section>
  );
}
