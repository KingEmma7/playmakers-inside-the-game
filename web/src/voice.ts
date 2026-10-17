import { useEffect, useRef } from "react";
import { recapText } from "./recapText";
import type { MatchEvent, OverlayCue } from "./stream";
import { whatIfQuestion } from "./whatifCopy";

export type Language = "en" | "es" | "fr";
export interface Speaker {
  readonly name: "browser" | "azure";
  speak(text: string, language: Language): Promise<void>;
  cancel(): void;
}

const LOCALES: Record<Language, string> = {
  en: "en-GB",
  es: "es-ES",
  fr: "fr-FR",
};

export class BrowserSpeaker implements Speaker {
  readonly name = "browser";
  speak(text: string, language: Language) {
    return new Promise<void>((resolve) => {
      if (!("speechSynthesis" in window)) return resolve();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = LOCALES[language];
      utterance.onend = () => resolve();
      utterance.onerror = () => resolve();
      window.speechSynthesis.speak(utterance);
    });
  }
  cancel() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }
}

export class AzureSpeaker implements Speaker {
  readonly name = "azure";
  private audio?: HTMLAudioElement;
  constructor(private readonly apiBase: string) {}
  async speak(text: string, language: Language) {
    const query = new URLSearchParams({ text, language });
    const response = await fetch(`${this.apiBase}/speech/synthesize?${query}`, {
      headers: { "X-Playmakers-Speech": "1" },
    });
    if (!response.ok) throw new Error(`Speech failed: ${response.status}`);
    const url = URL.createObjectURL(await response.blob());
    this.audio = new Audio(url);
    await new Promise<void>((resolve) => {
      if (!this.audio) return resolve();
      this.audio.onended = () => resolve();
      this.audio.onerror = () => resolve();
      void this.audio.play().catch(() => resolve());
    });
    URL.revokeObjectURL(url);
  }
  cancel() {
    this.audio?.pause();
  }
}

export async function chooseSpeaker(apiBase: string): Promise<Speaker> {
  try {
    const response = await fetch(`${apiBase}/speech/config`);
    const config: unknown = await response.json();
    if (
      typeof config === "object" &&
      config !== null &&
      "azure" in config &&
      config.azure === true
    )
      return new AzureSpeaker(apiBase);
  } catch {
    // The browser voice needs no backend.
  }
  return new BrowserSpeaker();
}

export const MIN_GAP_MS = 8000;
const STALE_MS = 5000;
const GOAL: Record<Language, string> = {
  en: "Goal for",
  es: "¡Gol de",
  fr: "But pour",
};
const TEAM = (teamId: string) =>
  teamId.endsWith("_HOME") ? "Northbridge Rovers" : "Southport Athletic";

const eventIdOf = (cue: OverlayCue) =>
  /^(.*?):(?:tactics|storyline|what_if|graphics|recap)(?::|$)/.exec(
    cue.cue_id,
  )?.[1];

export function priorityMoment(
  cue: OverlayCue,
  events: MatchEvent[],
): "recap" | "what_if" | "goal" | "red_card" | undefined {
  if (cue.template === "recap") return "recap";
  if (cue.template === "what_if") return "what_if";
  const eventId = eventIdOf(cue);
  const event = events.find((e) => e.event_id === eventId);
  if (event?.event_type === "goal") return "goal";
  if (event?.event_type === "card" && event.color === "red") return "red_card";
  return undefined;
}

export function spokenLine(cue: OverlayCue, events: MatchEvent[]): string {
  const language = cue.language ?? "en";
  const moment = priorityMoment(cue, events);
  if (moment === "recap")
    return recapText(cue).split("\n").slice(0, 2).join(" ");
  if (moment === "what_if") return whatIfQuestion(cue);
  const caption =
    `${String(cue.payload.headline ?? "")} ${String(cue.payload.detail ?? "")}`.trim();
  if (moment === "goal") {
    const goal = events.find((e) => e.event_id === eventIdOf(cue));
    const team = goal?.event_type === "goal" ? TEAM(goal.scoring_team_id) : "";
    return `${GOAL[language]} ${team}${language === "fr" ? " !" : "!"} ${caption}`;
  }
  return caption;
}

const RANK = { recap: 0, goal: 1, red_card: 1, what_if: 2 };
const rank = (cue: OverlayCue, events: MatchEvent[]) => {
  const moment = priorityMoment(cue, events);
  return moment ? RANK[moment] : 3;
};

export type VoiceState = {
  lastAt: number;
  speaking: boolean;
  spoken: Set<string>;
};

export function shouldSpeak(
  cue: OverlayCue,
  events: MatchEvent[],
  clock: number,
  now: number,
  state: VoiceState,
): boolean {
  const moment = priorityMoment(cue, events);
  if (!moment || state.spoken.has(cue.cue_id)) return false;
  if (clock - cue.clock_ms > STALE_MS) return false;
  if (moment === "recap") return true;
  return !state.speaking && now - state.lastAt >= MIN_GAP_MS;
}

export function useVoice({
  enabled,
  cues,
  events,
  clock,
  speaker,
}: {
  enabled: boolean;
  cues: OverlayCue[];
  events: MatchEvent[];
  clock: number;
  speaker?: Speaker;
}) {
  const state = useRef<VoiceState>({
    lastAt: -Infinity,
    speaking: false,
    spoken: new Set(),
  });
  useEffect(() => {
    if (!enabled || !speaker) return;
    const due = cues
      .filter(
        (c) =>
          c.persona === "casual" &&
          c.clock_ms <= clock &&
          shouldSpeak(c, events, clock, performance.now(), state.current),
      )
      .sort((a, b) => rank(a, events) - rank(b, events))[0];
    if (!due) return;
    const current = state.current;
    current.spoken.add(due.cue_id);
    if (current.speaking) speaker.cancel();
    current.speaking = true;
    current.lastAt = performance.now();
    void speaker
      .speak(spokenLine(due, events), due.language ?? "en")
      .catch(() => {})
      .finally(() => {
        current.speaking = false;
      });
  }, [enabled, cues, events, clock, speaker]);
  useEffect(() => {
    if (!enabled) speaker?.cancel();
  }, [enabled, speaker]);
}
