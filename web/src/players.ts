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

export function involvementLabel(
  events: MatchEvent[],
  favourite: string,
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
    ? `${shots} tiros`
    : passes
      ? `${passes} pases`
      : touches
        ? `${touches} toques`
        : "";
  return `${playerName(favourite)}${count ? ` · ${count}` : ""}`;
}
