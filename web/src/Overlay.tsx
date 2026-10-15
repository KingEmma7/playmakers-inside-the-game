import { involvementLabel, playerName } from "./players";
import Pitch from "./Pitch";
import { activeCues, type MatchEvent, type OverlayCue } from "./stream";
export function Crest({ away = false }: { away?: boolean }) {
  return <span className={`crest ${away ? "away" : ""}`} aria-hidden="true" />;
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
      <h3>
        {String(payload.headline || cue.template)
          .replaceAll("★", "")
          .trim()}
      </h3>
      <p>
        {whatif && cue.language === "es"
          ? {
              "if the shot had been saved":
                "¿Y si ese disparo se hubiera detenido?",
              "if the chance had been scored":
                "¿Y si esa ocasión hubiera sido gol?",
              "if the red card had not been shown":
                "¿Y si no hubiera habido tarjeta roja?",
            }[String(payload.scenario)] ||
            "¿Y si el desenlace hubiera sido diferente?"
          : String(payload.detail || "")}
      </p>
      {!whatif && (
        <small className="evidence" title={cue.evidence_event_ids.join(", ")}>
          {cue.language === "es" ? "Basado en los eventos" : "From events"}{" "}
          {cue.evidence_event_ids
            .slice(-3)
            .map((id) => String(Number(id.split(/[:_]/).at(-1))))
            .join(", ")}{" "}
          {cue.language === "es" ? "" : "· Verified"}
        </small>
      )}
      {Boolean(payload.player_cam) && (
        <div className="favourite">
          {playerName(String(record(payload.player_cam).player_id))} · favourite
          player
        </div>
      )}
      {whatif && (
        <>
          <div className="probability-summary">
            <small>
              {cue.language === "es"
                ? "Probabilidad de victoria"
                : "Win probability"}{" "}
              · {String(metrics.rollouts ?? "—")}{" "}
              {cue.language === "es" ? "simulaciones" : "simulations"}
            </small>
            <div className="probabilities">
              <span>
                {(Number(metrics.win_prob_before) * 100).toFixed(0)}%{" "}
                <small>Before</small>
              </span>
              <b>→</b>
              <span>
                {(Number(metrics.win_prob_after) * 100).toFixed(0)}%{" "}
                <small>After</small>
              </span>
              <strong>
                {Number(metrics.delta) >= 0 ? "+" : ""}
                {(Number(metrics.delta) * 100).toFixed(1)} pp
              </strong>
            </div>
          </div>
          <div className="delta-track">
            <span
              className="probability-marker"
              style={{ left: `${Number(metrics.win_prob_before) * 100}%` }}
            />
            <i
              style={{
                width: `${Math.min(100, Number(metrics.win_prob_after) * 100)}%`,
                background: "var(--home)",
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
  favourite = "H09",
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
  favourite?: string;
}) {
  const active = activeCues(cues, clock);
  // One winner per slot; incoming cues replace lower-priority captions instead of covering the pitch.
  const primary =
    active.find((c) => c.template !== "what_if") ??
    cues
      .filter((c) => c.template !== "what_if" && c.clock_ms <= clock)
      .sort((a, b) => b.clock_ms - a.clock_ms)[0];
  const whatif = cues
    .filter((c) => c.template === "what_if" && c.clock_ms <= clock)
    .sort((a, b) => b.clock_ms - a.clock_ms)[0];
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
        e.clock_ms <= clock,
    )
    .at(-1);
  const visibleEvents = events.filter(
    (e) => e.sequence <= (event?.sequence ?? -1),
  );
  const shots = visibleEvents.filter((e) => e.event_type === "shot");
  const homeXg = shots.reduce(
    (sum, e) =>
      sum +
      (e.event_type === "shot" && e.team_id?.endsWith("_HOME") ? e.xg : 0),
    0,
  );
  const awayXg = shots.reduce(
    (sum, e) =>
      sum +
      (e.event_type === "shot" && !e.team_id?.endsWith("_HOME") ? e.xg : 0),
    0,
  );
  const passes = visibleEvents.filter((e) => e.event_type === "pass");
  const homePasses = passes.filter((e) => e.team_id?.endsWith("_HOME")).length;
  const lastPass = passes.at(-1);
  const possession = visibleEvents.filter((e) => e.team_id);
  const homePossession =
    (possession.filter((e) => e.team_id?.endsWith("_HOME")).length /
      (possession.length || 1)) *
    100;
  const defensiveActions = visibleEvents.filter(
    (e) =>
      ["tackle", "interception", "foul"].includes(e.event_type) &&
      e.team_id?.endsWith("_HOME"),
  ).length;
  const territory = passes.filter(
    (e) =>
      e.event_type === "pass" &&
      (e.team_id?.endsWith("_HOME")
        ? e.end_position.x > 70
        : e.end_position.x < 35),
  );
  const fieldTilt =
    (territory.filter((e) => e.team_id?.endsWith("_HOME")).length /
      (territory.length || 1)) *
    100;
  const metrics = record(primary?.payload.metrics);
  const momentum = Number(metrics.home_momentum ?? 0);
  return (
    <section
      className={`view ${persona}`}
      aria-label={persona === "analyst" ? "ANALYST view" : "FAN view"}
    >
      <div className="view-heading">
        <div>
          <span className="view-dot" />
          {title}
          <small>
            {persona === "analyst"
              ? "Tactics and verified metrics"
              : `${primary?.language === "fr" ? "Français" : "Español"} · ${playerName(favourite)}`}
          </small>
        </div>
        <span className="connection">{status}</span>
      </div>
      <div className="broadcast">
        <Pitch
          event={event}
          running={running}
          favourite={persona === "casual" ? favourite : undefined}
          involvement={involvementLabel(visibleEvents, favourite)}
        />
        <div className="vignette" />
        {safe && (
          <div className="safe-guides">
            <span>90% broadcast safe</span>
          </div>
        )}
        {persona === "analyst" && lastPass?.event_type === "pass" && (
          <div className="pass-stat">
            <svg viewBox="0 0 100 60">
              <path
                d="M10 50 A40 40 0 0 1 90 50"
                pathLength="100"
                fill="none"
                stroke="var(--rule)"
                strokeWidth="5"
              />
              <path
                d="M10 50 A40 40 0 0 1 90 50"
                pathLength="100"
                fill="none"
                stroke="var(--home)"
                strokeWidth="5"
                strokeDasharray={`${lastPass.difficulty * 100} 100`}
              />
            </svg>
            <b>{lastPass.difficulty.toFixed(2)}</b>
            <small>Pass difficulty</small>
          </div>
        )}
        {persona === "analyst" && shot?.event_type === "shot" && (
          <div className="shot-card">
            <span>Shot quality</span>
            <b>
              {shot.xg.toFixed(2)} <small>xG</small>
            </b>
            <small>{playerName(shot.shooter_player_id)}</small>
          </div>
        )}
        {!event && (
          <div className="loading">
            Connecting to the Playmakers crew
            <span>Waiting for the synthetic match feed…</span>
          </div>
        )}
      </div>
      {persona === "analyst" && (
        <div className="stat-row" aria-label="Match metrics">
          <div>
            <b>{homeXg.toFixed(2)}</b>
            <span>xG · {awayXg.toFixed(2)}</span>
          </div>
          <div>
            <b>{homePossession.toFixed(0)}%</b>
            <span>Possession</span>
          </div>
          <div>
            <b>
              {defensiveActions
                ? ((passes.length - homePasses) / defensiveActions).toFixed(1)
                : "—"}
            </b>
            <span title="Opposition passes per home defensive action">
              PPDA · home
            </span>
          </div>
          <div>
            <b>{fieldTilt.toFixed(0)}%</b>
            <span>Field tilt · final third</span>
          </div>
        </div>
      )}
      <div className="lower-thirds">
        {primary && <CueCard key={primary.template} cue={primary} />}
        {persona === "casual" && whatif && (
          <CueCard key={whatif.cue_id} cue={whatif} />
        )}
        {!whatif && storyline && (
          <details className="storyline-detail">
            <summary>
              {String(storyline.payload.headline || "Storyline")}
            </summary>
            <CueCard key={storyline.template} cue={storyline} />
          </details>
        )}
      </div>
      {
        <div className="momentum">
          <div>
            <span>{persona === "casual" ? "Dominio" : "Dominance"}</span>
            <b>{momentum > 0 ? "NBR" : momentum < 0 ? "SPA" : "EVEN"}</b>
          </div>
          <svg
            className="dominance-bars"
            viewBox="0 0 320 32"
            preserveAspectRatio="none"
            role="img"
            aria-label="Recent possession by team"
          >
            <line x1="0" y1="16" x2="320" y2="16" stroke="var(--rule)" />
            {events
              .filter((e) => e.sequence <= (event?.sequence ?? -1) && e.team_id)
              .slice(-32)
              .map((e, i) => {
                const home = e.team_id?.endsWith("_HOME");
                const height =
                  e.event_type === "shot" || e.event_type === "goal"
                    ? 14
                    : e.event_type === "pass"
                      ? 8
                      : 4;
                return (
                  <rect
                    key={e.event_id}
                    x={i * 10}
                    y={home ? 16 - height : 16}
                    width="8"
                    height={height}
                    fill={home ? "var(--home)" : "var(--away)"}
                  />
                );
              })}
          </svg>
        </div>
      }
    </section>
  );
}
