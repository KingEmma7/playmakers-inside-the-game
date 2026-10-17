import type { OverlayCue } from "./stream";

const SPANISH: Record<string, string> = {
  "if the shot had been saved": "¿Y si ese disparo se hubiera detenido?",
  "if the chance had been scored": "¿Y si esa ocasión hubiera sido gol?",
  "if the red card had not been shown": "¿Y si no hubiera habido tarjeta roja?",
};

export function whatIfQuestion(cue: OverlayCue): string {
  if (cue.language === "es")
    return (
      SPANISH[String(cue.payload.scenario)] ||
      "¿Y si el desenlace hubiera sido diferente?"
    );
  return String(cue.payload.detail || "");
}
