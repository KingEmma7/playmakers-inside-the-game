import type { MatchEvent } from "./stream";
const home = [
  "Ellis",
  "Mensah",
  "Costa",
  "Reed",
  "Diallo",
  "Vega",
  "Hale",
  "Silva",
  "Okafor",
  "Marin",
  "Sato",
];
const away = [
  "Bello",
  "Novak",
  "Duarte",
  "Chen",
  "Amari",
  "Solis",
  "Luka",
  "Keita",
  "Santos",
  "Moreau",
  "Ivers",
];
export function playerName(id: string): string {
  const code = id.split("_").at(-1) || "H09";
  return (
    (code.startsWith("A") ? away : home)[Number(code.slice(1)) - 1] || "Okafor"
  );
}

type Language = "en" | "es" | "fr";
const COUNT_WORDS: Record<
  Language,
  Record<"shot" | "pass" | "touch", [string, string]>
> = {
  en: { shot: ["shot", "shots"], pass: ["pass", "passes"], touch: ["touch", "touches"] },
  es: { shot: ["tiro", "tiros"], pass: ["pase", "pases"], touch: ["toque", "toques"] },
  fr: { shot: ["tir", "tirs"], pass: ["passe", "passes"], touch: ["touche", "touches"] },
};
export const isLanguage = (value: string): value is Language =>
  value === "en" || value === "es" || value === "fr";
export function countLabel(
  count: number,
  kind: "shot" | "pass" | "touch",
  language: string = "en",
): string {
  const [one, many] = COUNT_WORDS[isLanguage(language) ? language : "en"][kind];
  return `${count} ${count === 1 ? one : many}`;
}

export function involvementLabel(
  events: MatchEvent[],
  favourite: string,
  language: string = "en",
): string {
  const matches = (id: string | null | undefined) =>
    id?.split("_").at(-1) === favourite;
  const shots = events.filter(
    (e) => e.event_type === "shot" && matches(e.shooter_player_id),
  ).length;
  const passes = events.filter(
    (e) => e.event_type === "pass" && matches(e.from_player_id),
  ).length;
  const touches = events.filter(
    (e) =>
      matches(e.player_id) ||
      (e.event_type === "pass" &&
        (matches(e.from_player_id) || matches(e.to_player_id))) ||
      (e.event_type === "shot" && matches(e.shooter_player_id)),
  ).length;
  const count = shots
    ? countLabel(shots, "shot", language)
    : passes
      ? countLabel(passes, "pass", language)
      : touches
        ? countLabel(touches, "touch", language)
        : "";
  return `${playerName(favourite)}${count ? ` · ${count}` : ""}`;
}
