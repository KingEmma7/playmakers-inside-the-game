import type { CueProvenance } from "./generated/OverlayCue";
import type { MatchEvent, OverlayCue } from "./stream";

const COPY = {
  en: {
    why: "Why?",
    close: "Close",
    agent: {
      tactics: "Tactics agent",
      storyline: "Storyline agent",
      what_if: "What-If agent",
      graphics: "Graphics agent",
    },
    events: "Supporting events",
    stats: "Stats used",
    verified:
      "Compliance verified it: every number matches the stats engine and every cited event exists.",
    templated:
      "A routine moment, so no model was called: a rule wrote this from verified stats, and Compliance checked every number.",
    corrected: (rejected: number, reason: string) =>
      `Compliance rejected ${rejected} draft${rejected > 1 ? "s" : ""} (${reason}), then verified the correction.`,
    fallback: (reason: string) =>
      `Compliance blocked the agent's output (${reason}). A safe template ran instead.`,
    simulated: (rollouts: string) =>
      `Computed from ${rollouts} seeded simulations of the rest of the match. Not reviewed by Compliance; the explanation may not contain numbers.`,
    rewritten: (headline: string) =>
      `Rewritten for fans by the Audience agent from “${headline}”.`,
  },
  es: {
    why: "¿Por qué?",
    close: "Cerrar",
    agent: {
      tactics: "Agente de táctica",
      storyline: "Agente de relato",
      what_if: "Agente ¿Y si…?",
      graphics: "Agente de gráficos",
    },
    events: "Eventos de apoyo",
    stats: "Datos usados",
    verified:
      "Compliance lo verificó: cada número coincide con el motor de estadísticas y cada evento citado existe.",
    templated:
      "Jugada rutinaria, sin llamada al modelo: una regla lo escribió con datos verificados y Compliance revisó cada número.",
    corrected: (rejected: number, reason: string) =>
      `Compliance rechazó ${rejected} borrador${rejected > 1 ? "es" : ""} (${reason}) y luego verificó la corrección.`,
    fallback: (reason: string) =>
      `Compliance bloqueó la respuesta del agente (${reason}). Se usó una plantilla segura.`,
    simulated: (rollouts: string) =>
      `Calculado con ${rollouts} simulaciones del resto del partido. Compliance no lo revisa; la explicación no puede contener números.`,
    rewritten: (headline: string) =>
      `Adaptado para fans por el agente de audiencia a partir de “${headline}”.`,
  },
  fr: {
    why: "Pourquoi ?",
    close: "Fermer",
    agent: {
      tactics: "Agent tactique",
      storyline: "Agent récit",
      what_if: "Agent Et si… ?",
      graphics: "Agent graphique",
    },
    events: "Événements à l'appui",
    stats: "Données utilisées",
    verified:
      "Compliance l'a vérifié : chaque chiffre correspond au moteur de statistiques et chaque événement cité existe.",
    templated:
      "Action de routine, sans appel au modèle : une règle l'a rédigé à partir de statistiques vérifiées, et Compliance a contrôlé chaque chiffre.",
    corrected: (rejected: number, reason: string) =>
      `Compliance a rejeté ${rejected} brouillon${rejected > 1 ? "s" : ""} (${reason}), puis a vérifié la correction.`,
    fallback: (reason: string) =>
      `Compliance a bloqué la réponse de l'agent (${reason}). Un modèle sûr a été utilisé.`,
    simulated: (rollouts: string) =>
      `Calculé à partir de ${rollouts} simulations de la fin du match. Non revu par Compliance ; l'explication ne peut pas contenir de chiffres.`,
    rewritten: (headline: string) =>
      `Réécrit pour les fans par l'agent audience à partir de « ${headline} ».`,
  },
} as const;

const copyFor = (language?: string | null) =>
  COPY[language === "es" || language === "fr" ? language : "en"];

function verdict(provenance: CueProvenance, language?: string | null) {
  const copy = copyFor(language);
  const reason = provenance.reasons?.[0] ?? "";
  if (provenance.compliance === "not_reviewed")
    return copy.simulated(String(provenance.metrics?.rollouts ?? "—"));
  if (provenance.compliance === "template_fallback")
    return copy.fallback(reason);
  if (provenance.source === "template") return copy.templated;
  const attempts = provenance.attempts ?? 1;
  return attempts > 1 ? copy.corrected(attempts - 1, reason) : copy.verified;
}

const eventNumber = (id: string) =>
  String(Number(/(\d+)$/.exec(id)?.[1] ?? id));
const clockLabel = (ms: number) =>
  `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;
const MAX_CHIPS = 6;
const MAX_STATS = 4;
const formatValue = (key: string, value: unknown) =>
  typeof value !== "number"
    ? String(value)
    : key.startsWith("win_prob")
      ? `${Math.round(value * 100)}%`
      : Number.isInteger(value)
        ? String(value)
        : value.toFixed(2);
const evidenceLabel = (ids: string[]) =>
  ids.length > 3
    ? `${ids.length} events`
    : `#${ids.map(eventNumber).join(", #")}`;

export function ProvenancePanel({
  cue,
  events,
  focus,
  onFocus,
  onClose,
}: {
  cue: OverlayCue;
  events: MatchEvent[];
  focus?: string;
  onFocus: (eventId?: string) => void;
  onClose: () => void;
}) {
  const provenance = cue.provenance;
  const copy = copyFor(cue.language);
  if (!provenance) return null;
  const cited = cue.evidence_event_ids
    .map((id) => events.find((e) => e.event_id === id))
    .filter(
      (e): e is MatchEvent =>
        e !== undefined && e.event_type !== "tracking_frame",
    );
  const shown = cited.slice(-MAX_CHIPS);
  const metrics = Object.entries(provenance.metrics ?? {}).slice(0, MAX_STATS);
  return (
    <section
      className="provenance"
      role="dialog"
      aria-label={`${copy.agent[provenance.agent]}: ${copy.why}`}
    >
      <div className="provenance-head">
        <h3>{copy.agent[provenance.agent]}</h3>
        <button type="button" onClick={onClose}>
          {copy.close}
        </button>
      </div>
      <p className={`verdict ${provenance.compliance}`}>
        {verdict(provenance, cue.language)}
      </p>
      {provenance.personalized_for === "casual" &&
        provenance.insight_headline && (
          <p>{copy.rewritten(provenance.insight_headline)}</p>
        )}
      {cited.length > 0 && (
        <div className="provenance-row">
          <span>{copy.events}</span>
          <div className="event-chips">
            {shown.map((e) => (
              <button
                type="button"
                key={e.event_id}
                aria-pressed={focus === e.event_id}
                onClick={() =>
                  onFocus(focus === e.event_id ? undefined : e.event_id)
                }
              >
                #{eventNumber(e.event_id)} {e.event_type.replaceAll("_", " ")} ·{" "}
                {clockLabel(e.clock_ms)}
              </button>
            ))}
            {cited.length > shown.length && (
              <small>+{cited.length - shown.length}</small>
            )}
          </div>
        </div>
      )}
      {metrics.length > 0 && (
        <div className="provenance-row">
          <span>{copy.stats}</span>
          <ul className="provenance-stats">
            {metrics.map(([key, value]) => (
              <li key={key}>
                {key.replaceAll("_", " ")} <b>{formatValue(key, value)}</b>
                {provenance.metric_evidence?.[key] && (
                  <small>
                    {" "}
                    · {evidenceLabel(provenance.metric_evidence[key])}
                  </small>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
