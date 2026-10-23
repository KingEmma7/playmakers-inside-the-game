import type { OverlayCue } from "./stream";
import { playerName } from "./players";

export function whatIfQuestion(cue: OverlayCue): string {
  const { scenario, moment, metrics, win_team_id } = cue.payload;
  const data = moment as { player_id?: string; minute?: number } | undefined;
  const odds = metrics as Record<string, number> | undefined;
  if (
    !data?.player_id ||
    typeof data.minute !== "number" ||
    typeof odds?.win_prob_after !== "number" ||
    typeof odds.win_prob_counterfactual !== "number" ||
    !win_team_id
  )
    return String(cue.payload.detail || "");
  const player = playerName(data.player_id);
  const minute = `${data.minute}'`;
  const actual = Math.round(odds.win_prob_after * 100);
  const alternative = Math.round(odds.win_prob_counterfactual * 100);
  const phrases: Record<string, Record<string, string>> = {
    en: {
      "if the shot had been saved": `If ${player}'s ${minute} shot had been saved`,
      "if the chance had been scored": `If ${player}'s ${minute} chance had been scored`,
      "if the red card had not been shown": `If ${player}'s ${minute} red card had not been shown`,
    },
    es: {
      "if the shot had been saved": `Si el disparo de ${player} en el ${minute} hubiera sido detenido`,
      "if the chance had been scored": `Si la ocasión de ${player} en el ${minute} hubiera sido gol`,
      "if the red card had not been shown": `Si no se hubiera mostrado la roja a ${player} en el ${minute}`,
    },
    fr: {
      "if the shot had been saved": `Si le tir de ${player} à la ${minute} avait été arrêté`,
      "if the chance had been scored": `Si l'occasion de ${player} à la ${minute} avait été convertie`,
      "if the red card had not been shown": `Si le carton rouge de ${player} à la ${minute} n'avait pas été montré`,
    },
  };
  const language = cue.language ?? "en";
  const opening = (phrases[language] ?? phrases.en)[String(scenario)];
  if (!opening) return String(cue.payload.detail || "");
  if (language === "es")
    return `${opening}: probabilidad de victoria ${alternative}% en vez de ${actual}%.`;
  if (language === "fr")
    return `${opening} : chances de victoire ${alternative}% au lieu de ${actual}%.`;
  return `${opening}: win chance ${alternative}% instead of ${actual}%.`;
}
