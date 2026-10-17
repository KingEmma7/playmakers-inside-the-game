import { playerName } from "./players";
import type { OverlayCue } from "./stream";

export type Moment = {
  clock_ms: number;
  event_id: string;
  kind: "goal" | "red_card" | "big_chance" | "chance";
  team_id?: string;
  player_id?: string;
  xg?: number;
};
const KINDS = ["goal", "red_card", "big_chance", "chance"] as const;
const isKind = (value: unknown): value is Moment["kind"] =>
  KINDS.some((kind) => kind === value);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function recapMoments(payload: Record<string, unknown>): Moment[] {
  const raw = Array.isArray(payload.moments) ? payload.moments : [];
  return raw.flatMap((m: unknown) =>
    isRecord(m) &&
    typeof m.clock_ms === "number" &&
    typeof m.event_id === "string" &&
    isKind(m.kind)
      ? [
          {
            clock_ms: m.clock_ms,
            event_id: m.event_id,
            kind: m.kind,
            team_id: typeof m.team_id === "string" ? m.team_id : undefined,
            player_id:
              typeof m.player_id === "string" ? m.player_id : undefined,
            xg: typeof m.xg === "number" ? m.xg : undefined,
          },
        ]
      : [],
  );
}

export const RECAP_COPY = {
  en: {
    goal: "Goal",
    red_card: "Red card",
    big_chance: "Big chance",
    chance: "Chance",
    copy: "Copy",
    share: "Share",
    copied: "Copied",
    label: "Full-time recap",
    why: "Why?",
  },
  es: {
    goal: "Gol",
    red_card: "Tarjeta roja",
    big_chance: "Ocasión clara",
    chance: "Ocasión",
    copy: "Copiar",
    share: "Compartir",
    copied: "Copiado",
    label: "Resumen del partido",
    why: "¿Por qué?",
  },
  fr: {
    goal: "But",
    red_card: "Carton rouge",
    big_chance: "Grosse occasion",
    chance: "Occasion",
    copy: "Copier",
    share: "Partager",
    copied: "Copié",
    label: "Résumé du match",
    why: "Pourquoi ?",
  },
};
const teamName = (teamId?: string) =>
  teamId?.endsWith("_HOME") ? "Northbridge Rovers" : "Southport Athletic";
export const minute = (ms: number) => `${Math.floor(ms / 60000) + 1}'`;

export function momentLabel(m: Moment, language: string, analyst: boolean) {
  const copy =
    RECAP_COPY[language === "es" || language === "fr" ? language : "en"];
  const who = m.player_id ? ` (${playerName(m.player_id)})` : "";
  const xg = analyst && m.xg !== undefined ? ` · ${m.xg.toFixed(2)} xG` : "";
  return `${copy[m.kind]} · ${teamName(m.team_id)}${who}${xg}`;
}

export function recapText(cue: OverlayCue) {
  const analyst = cue.persona !== "casual";
  return [
    String(cue.payload.headline ?? ""),
    String(cue.payload.detail ?? ""),
    ...recapMoments(cue.payload).map(
      (m) =>
        `${minute(m.clock_ms)} ${momentLabel(m, cue.language ?? "en", analyst)}`,
    ),
  ].join("\n");
}
