import AskCrew from "./AskCrew";
import LoadingState from "./LoadingState";
import { useState } from "react";
import { involvementLabel, playerName } from "./players";

const CARD_LABELS: Record<
  string,
  {
    evidence: string;
    verified: string;
    winProbability: string;
    simulations: string;
    dominance: string;
    even: string;
  }
> = {
  en: {
    evidence: "From events",
    verified: "· Verified",
    winProbability: "Win probability",
    simulations: "simulations",
    dominance: "Dominance",
    even: "EVEN",
  },
  es: {
    evidence: "Basado en los eventos",
    verified: "· Verificado",
    winProbability: "Probabilidad de victoria",
    simulations: "simulaciones",
    dominance: "Dominio",
    even: "IGUALADO",
  },
  fr: {
    evidence: "D'après les événements",
    verified: "· Vérifié",
    winProbability: "Probabilité de victoire",
    simulations: "simulations",
    dominance: "Domination",
    even: "ÉQUILIBRE",
  },
};
const labelsFor = (language?: string | null) =>
  CARD_LABELS[language ?? "en"] ?? CARD_LABELS.en;
// Possession and field tilt need a few minutes of events before a share means anything.
const MIN_POSSESSION_EVENTS = 30;
const MIN_TILT_PASSES = 10;
import Pitch from "./Pitch";
import { eventPoint, type Point } from "./geometry";
import { ProvenancePanel } from "./Provenance";
import { whatIfQuestion } from "./whatifCopy";
import { RecapCard } from "./Recap";
import { recapMoments } from "./recapText";
import { activeCues, type MatchEvent, type OverlayCue } from "./stream";
const WHATIF_HIGHLIGHT_MS = 120_000;
const WHY = { en: "Why?", es: "¿Por qué?", fr: "Pourquoi ?" };
export function Crest({ away = false }: { away?: boolean }) {
  return <span className={`crest ${away ? "away" : ""}`} aria-hidden="true" />;
}
const record = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
const SWING_LABELS: Record<string, [string, string]> = {
  en: ["What happened", "Alternative"],
  es: ["Lo que pasó", "Alternativa"],
  fr: ["Ce qui s'est passé", "Alternative"],
};
export function OddsSwing({
  actual,
  alternative,
  language,
}: {
  actual: number;
  alternative: number;
  language: string;
}) {
  const [actualLabel, alternativeLabel] =
    SWING_LABELS[language] ?? SWING_LABELS.en;
  const percent = (value: number) => Math.round(value * 100);
  const swing = percent(actual) - percent(alternative);
  const rows: [string, number, string][] = [
    [actualLabel, actual, "actual"],
    [alternativeLabel, alternative, "alternative"],
  ];
  return (
    <div
      className="odds-swing"
      role="img"
      aria-label={`${actualLabel} ${percent(actual)}%, ${alternativeLabel} ${percent(alternative)}%`}
    >
      {rows.map(([label, value, kind]) => (
        <div className={`odds-row ${kind}`} key={kind}>
          <span>{label}</span>
          <div className="odds-bar">
            <i
              style={{ width: `${Math.max(1, Math.min(100, value * 100))}%` }}
            />
          </div>
          <b>{percent(value)}%</b>
        </div>
      ))}
      <strong className="odds-delta">
        {swing > 0 ? "+" : swing < 0 ? "−" : "±"}
        {Math.abs(swing)} pts
      </strong>
    </div>
  );
}
export function CueCard({
  cue,
  onExplain,
  referenced = false,
}: {
  cue: OverlayCue;
  referenced?: boolean;
  onExplain?: () => void;
}) {
  const why =
    onExplain && cue.provenance ? (
      <button type="button" className="why" onClick={onExplain}>
        {WHY[cue.language ?? "en"]}
      </button>
    ) : null;
  const payload = cue.payload;
  const metrics = record(payload.metrics);
  const whatif = cue.template === "what_if";
  const swing =
    typeof metrics.win_prob_counterfactual === "number"
      ? {
          actual: Number(metrics.win_prob_after),
          alternative: metrics.win_prob_counterfactual,
        }
      : undefined;
  return (
    <article
      className={`cue ${referenced ? "referenced-event" : ""} ${whatif ? "whatif" : ""} ${cue.template === "template_fallback" ? "fallback" : ""}`}
      style={{ zIndex: (cue.priority ?? 0) + 1 }}
      data-testid="cue-card"
    >
      <h3>
        {String(payload.headline || cue.template)
          .replaceAll("★", "")
          .trim()}
      </h3>
      <p>{whatif ? whatIfQuestion(cue) : String(payload.detail || "")}</p>
      {!whatif && (
        <small className="evidence" title={cue.evidence_event_ids.join(", ")}>
          {labelsFor(cue.language).evidence}{" "}
          {cue.evidence_event_ids
            .slice(-3)
            .map((id) => String(Number(id.split(/[:_]/).at(-1))))
            .join(", ")}{" "}
          {cue.provenance?.compliance === "template_fallback"
            ? ""
            : labelsFor(cue.language).verified}{" "}
          {why}
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
              {labelsFor(cue.language).winProbability} ·{" "}
              {String(metrics.rollouts ?? "—")}{" "}
              {labelsFor(cue.language).simulations} {why}
            </small>
            {!swing && (
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
            )}
          </div>
          {!swing ? (
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
          ) : (
            <OddsSwing
              actual={swing.actual}
              alternative={swing.alternative}
              language={cue.language ?? "en"}
            />
          )}
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
  seed = 382,
  persona,
  event,
  events,
  cues,
  clock,
  safe,
  running,
  status,
  favourite = "H09",
  language = "en",
  citedIds,
  onCitations,
}: {
  title: string;
  seed?: number;
  persona: string;
  event?: MatchEvent;
  events: MatchEvent[];
  cues: OverlayCue[];
  clock: number;
  safe: boolean;
  running: boolean;
  status: string;
  favourite?: string;
  language?: string;
  citedIds?: string[];
  onCitations?: (ids: string[] | undefined) => void;
}) {
  const [explained, setExplained] = useState<OverlayCue>();
  const [localAskIds, setLocalAskIds] = useState<string[]>();
  const askIds = onCitations ? citedIds : localAskIds;
  const setAskIds = onCitations ?? setLocalAskIds;
  const [focus, setFocus] = useState<string>();
  const explain = (cue: OverlayCue) => () => {
    setAskIds(undefined);
    setExplained(cue);
    setFocus(undefined);
  };
  const active = activeCues(cues, clock);
  // One winner per slot; incoming cues replace lower-priority captions instead of covering the pitch.
  const heldMoment = cues
    .filter(
      (c) =>
        c.template !== "what_if" &&
        (c.payload.moment === "goal" || c.payload.moment === "card") &&
        c.clock_ms <= clock &&
        clock < c.clock_ms + Number(c.payload.hold_ms ?? 60000),
    )
    .sort((a, b) => b.clock_ms - a.clock_ms)
    .at(0);
  const heldThreat = cues.filter((c) => c.template === "goal_threat" &&
    c.clock_ms <= clock && clock < c.clock_ms + Number(c.payload.hold_ms ?? 30000)).at(-1);
  const primary =
    heldMoment ?? heldThreat ??
    active.find((c) => c.template !== "what_if" && c.template !== "recap") ??
    cues
      .filter(
        (c) =>
          c.template !== "what_if" &&
          c.template !== "recap" &&
          c.clock_ms <= clock,
      )
      .sort((a, b) => b.clock_ms - a.clock_ms)[0];
  const whatif = cues
    .filter((c) => persona === "analyst" && c.template === "what_if" && c.clock_ms <= clock)
    .sort((a, b) => b.clock_ms - a.clock_ms)[0];
  const recap = cues
    .filter((c) => c.template === "recap" && c.clock_ms <= clock)
    .at(-1);
  const highlighted = askIds ?? (focus
    ? [focus]
    : explained
      ? explained.evidence_event_ids
      : recap
        ? recapMoments(recap.payload).map((m) => m.event_id)
        : whatif && clock - whatif.clock_ms <= WHATIF_HIGHLIGHT_MS
          ? whatif.evidence_event_ids
          : []);
  const trail = highlighted
    .map((id) => events.find((e) => e.event_id === id))
    .map((e) =>
      e?.event_type === "goal"
        ? events.find((s) => s.event_id === e.shot_event_id)
        : e,
    )
    .filter((e) => e && e.event_type !== "tracking_frame")
    .map(eventPoint)
    .filter((point): point is Point => point !== undefined);
  const storyline = !heldMoment && active.find(
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
  const threats = cues.filter((c) => c.clock_ms <= clock && c.goal_threat?.length).at(-1)?.goal_threat ?? [];
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
          <small className="view-subtitle">
            {persona === "analyst"
              ? "Tactics and verified metrics"
              : `${{ en: "English", es: "Español", fr: "Français" }[primary?.language ?? language]} · ${playerName(favourite)}`}
          </small>
          {/* The analyst's live cards sit in the heading strip, never on top of the pitch. */}
          {persona === "analyst" && (
            <span className="pitch-strip" aria-label="Last pass and shot">
              <span className="pass-stat">
                <small>
                  <span className="long">Pass difficulty</span>
                  <span className="short">Pass</span>
                </small>
                <b>
                  {lastPass?.event_type === "pass"
                    ? lastPass.difficulty.toFixed(2)
                    : "—"}
                </b>
              </span>
              <span className="shot-card">
                <b>
                  {shot?.event_type === "shot" ? shot.xg.toFixed(2) : "—"}{" "}
                  <small>xG</small>
                </b>
                {shot?.event_type === "shot" && (
                  <small className="shooter">
                    {playerName(shot.shooter_player_id)}
                  </small>
                )}
              </span>
            </span>
          )}
        </div>
        <span className="connection">{status}</span>
      </div>
      <div className="match-content">
        <div className="broadcast">
          <Pitch
            events={visibleEvents}
            running={running}
            favourite={persona === "casual" ? favourite : undefined}
            involvement={involvementLabel(visibleEvents, favourite, language)}
            trail={trail}
          />
          <div className="vignette" />
          {safe && (
            <div className="safe-guides">
              <span>90% broadcast safe</span>
            </div>
          )}
        </div>
        <div className="pitch-legend" aria-label="Pitch marks">
          <span><svg viewBox="0 0 24 16" aria-hidden="true"><path d="M2 8h20" /></svg>Pass</span>
          <span><svg viewBox="0 0 24 16" aria-hidden="true"><path d="M2 8h20" strokeDasharray="3 3" /></svg>Incomplete pass</span>
          <span><svg viewBox="0 0 24 16" aria-hidden="true"><circle cx="12" cy="8" r="6" strokeDasharray="2 2" /></svg>Referenced event</span>
          <span><svg className="latest-event" viewBox="0 0 24 16" aria-hidden="true"><circle cx="12" cy="8" r="6" strokeDasharray="2 2" /></svg>Latest referenced</span>
        </div>
        <div className={`view-body ${explained || recap ? "explaining" : ""}`}>
          {!explained && recap && (
            <RecapCard
              cue={recap}
              focus={focus}
              onFocus={setFocus}
              onExplain={explain(recap)}
            />
          )}
          {explained && (
            <ProvenancePanel
              cue={explained}
              events={events}
              focus={focus}
              onFocus={setFocus}
              onClose={() => {
                setExplained(undefined);
                setFocus(undefined);
              }}
            />
          )}
          {persona === "analyst" && (
            <div className="stat-row" aria-label="Match metrics">
              <div>
                <b>{homeXg.toFixed(2)}</b>
                <span>xG · {awayXg.toFixed(2)}</span>
              </div>
              <div>
                <b>
                  {possession.length < MIN_POSSESSION_EVENTS
                    ? "—"
                    : `${homePossession.toFixed(0)}%`}
                </b>
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
                <b>
                  {territory.length < MIN_TILT_PASSES
                    ? "—"
                    : `${fieldTilt.toFixed(0)}%`}
                </b>
                <span>Field tilt · final third</span>
              </div>
            </div>
          )}
          {persona === "analyst" && threats.length > 0 && (
            <div className="goal-threat" aria-label="Goal threat">
              {threats.map((threat) => <p key={threat.team_id}>
                Goal threat: {threat.level}, {threat.team_id.endsWith("_HOME") ? "Northbridge" : "Southport"}
                <span className="goal-threat-probability"> · {(threat.probability * 100).toFixed(1)}% in next 5 min</span>
              </p>)}
            </div>
          )}
          <div className="lower-thirds">
            {primary && (
              <CueCard
                key={primary.template}
                referenced={primary.evidence_event_ids.some((id) => askIds?.includes(id))}
                cue={primary}
                onExplain={explain(primary)}
              />
            )}
            {persona === "analyst" && whatif && (
              <CueCard
                key={whatif.cue_id}
                referenced={whatif.evidence_event_ids.some((id) => askIds?.includes(id))}
                cue={whatif}
                onExplain={explain(whatif)}
              />
            )}
            {!whatif && storyline && (
              <details className="storyline-detail">
                <summary>
                  {String(storyline.payload.headline || "Storyline")}
                </summary>
                <CueCard
                  key={storyline.template}
                  cue={storyline}
                  onExplain={explain(storyline)}
                />
              </details>
            )}
          </div>
          {
            <div className="momentum">
              <div>
                <span>
                  {labelsFor(persona === "casual" ? language : "en").dominance}
                </span>
                <b>
                  {momentum > 0
                    ? "NBR"
                    : momentum < 0
                      ? "SPA"
                      : labelsFor(persona === "casual" ? language : "en").even}
                </b>
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
                  .filter(
                    (e) => e.sequence <= (event?.sequence ?? -1) && e.team_id,
                  )
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
          {persona === "casual" && <AskCrew
            key={`${seed}-${language}`}
            seed={seed} uptoEventId={event?.event_id} language={language}
            onCitations={(ids) => { setAskIds(ids.length ? ids : undefined); setExplained(undefined); setFocus(undefined); }}
          />}
        </div>
        <LoadingState waiting={!event} reconnecting={status === "reconnecting"} />
      </div>
    </section>
  );
}
