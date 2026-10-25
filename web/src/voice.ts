import { useEffect, useRef } from "react";
import { recapText } from "./recapText";
import type { MatchEvent, OverlayCue, Trace } from "./stream";
import { whatIfQuestion } from "./whatifCopy";

export type Language = "en" | "es" | "fr";
export type Emphasis = "normal" | "goal" | "big";
export interface Speaker {
  readonly name: "browser" | "azure";
  speak(text: string, language: Language, emphasis?: Emphasis): Promise<void>;
  cancel(): void;
}
const LOCALES = { en: "en-GB", es: "es-ES", fr: "fr-FR" };

export class BrowserSpeaker implements Speaker {
  readonly name = "browser";
  private finish?: () => void;
  speak(text: string, language: Language, emphasis: Emphasis = "normal") {
    return new Promise<void>((resolve) => {
      if (!("speechSynthesis" in window)) return resolve();
      this.finish = resolve;
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = LOCALES[language];
      const voices = window.speechSynthesis.getVoices?.() ?? [];
      utterance.voice = voices.find((v) => v.lang === utterance.lang) ??
        voices.find((v) => v.lang.startsWith(language)) ?? null;
      utterance.rate = emphasis === "goal" ? 1.12 : 1.05;
      utterance.pitch = emphasis === "goal" ? 1.12 : emphasis === "big" ? 1.06 : 1;
      utterance.onend = () => resolve();
      utterance.onerror = () => resolve();
      window.speechSynthesis.speak(utterance);
    });
  }
  cancel() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    this.finish?.();
  }
}

export class AzureSpeaker implements Speaker {
  readonly name = "azure";
  private audio?: HTMLAudioElement;
  private controller?: AbortController;
  private finish?: () => void;
  private generation = 0;
  private failed = false;
  constructor(private readonly apiBase: string, private readonly fallback: Speaker = new BrowserSpeaker()) {}
  async speak(text: string, language: Language, emphasis: Emphasis = "normal") {
    if (this.failed) return this.fallback.speak(text, language, emphasis);
    const generation = this.generation;
    this.controller = new AbortController();
    let url: string | undefined;
    try {
      const response = await fetch(`${this.apiBase}/speech/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, language, emphasis }),
        signal: this.controller.signal,
      });
      if (!response.ok) throw new Error(`Speech failed: ${response.status}`);
      const blob = await response.blob();
      if (generation !== this.generation) return;
      url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      this.audio = audio;
      await new Promise<void>((resolve, reject) => {
        this.finish = resolve;
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error("Audio failed"));
        void audio.play().catch(reject);
      });
    } catch {
      if (generation !== this.generation) return;
      this.failed = true;
      await this.fallback.speak(text, language, emphasis);
    } finally {
      if (url) URL.revokeObjectURL(url);
    }
  }
  cancel() {
    this.generation++;
    this.controller?.abort();
    this.audio?.pause();
    this.finish?.();
    this.fallback.cancel();
  }
}

export async function chooseSpeaker(apiBase: string): Promise<Speaker> {
  try {
    const response = await fetch(`${apiBase}/speech/config`);
    const config: unknown = await response.json();
    if (response.ok && typeof config === "object" && config !== null &&
      "azure" in config && config.azure === true) return new AzureSpeaker(apiBase);
  } catch { /* The browser voice needs no backend. */ }
  return new BrowserSpeaker();
}
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
  const moment = priorityMoment(cue, events);
  if (moment === "recap")
    return recapText(cue).split("\n").join(" ");
  if (moment === "what_if") return whatIfQuestion(cue);
  return `${String(cue.payload.headline ?? "")} ${String(cue.payload.detail ?? "")}`.trim();
}

export type CommentaryLine = {
  id: string;
  text: string;
  language: Language;
  priority: "key" | "routine";
  emphasis: Emphasis;
};
type Pending = CommentaryLine & { at: number; count: number };
export type CommentaryDebug = { spoken: number; dropped: number; log: string[] };
declare global {
  interface Window { __playmakersCommentary?: CommentaryDebug }
}

/** Pure scheduling: callers supply the wall clock, speaker, arrivals and ticks. */
export class CommentaryQueue {
  readonly stats: CommentaryDebug = { spoken: 0, dropped: 0, log: [] };
  private pending: Pending[] = [];
  private busy = false;
  private generation = 0;
  private speed = 10;
  constructor(
    private readonly speaker: Speaker,
    private readonly now: () => number,
    private readonly staleMs = 8000,
    private readonly maxLength = 32,
  ) {}
  get length() { return this.pending.length; }
  setSpeed(speed: number) { this.speed = speed; this.prune(); }
  enqueue(line: CommentaryLine) {
    this.prune();
    if (line.priority === "routine" && this.speed >= 50) {
      this.stats.dropped++;
      return;
    }
    if (this.pending.length >= this.maxLength) {
      const routine = this.pending.findIndex((l) => l.priority === "routine");
      if (routine >= 0) {
        this.pending.splice(routine, 1);
        this.stats.dropped++;
      } else if (line.priority === "routine") {
        this.stats.dropped++;
        return;
      } else {
        // Preserve every key line, coalescing a key-only burst into one utterance.
        const last = this.pending[this.pending.length - 1];
        last.text += ` ${line.text}`;
        last.count++;
        if (line.emphasis === "goal") last.emphasis = "goal";
        return;
      }
    }
    this.pending.push({ ...line, at: this.now(), count: 1 });
  }
  private prune() {
    this.pending = this.pending.filter((line) => {
      const drop = line.priority === "routine" &&
        (this.speed >= 50 || this.now() - line.at > this.staleMs);
      if (drop) this.stats.dropped += line.count;
      return !drop;
    });
  }
  tick() {
    this.prune();
    if (this.busy) return;
    const key = this.pending.findIndex((l) => l.priority === "key");
    const line = this.pending.splice(key < 0 ? 0 : key, 1)[0];
    if (!line) return;
    this.busy = true;
    const generation = this.generation;
    void this.speaker.speak(line.text, line.language, line.emphasis).then(() => {
      if (generation !== this.generation) return;
      this.stats.spoken += line.count;
      this.stats.log.push(line.text);
      this.stats.log = this.stats.log.slice(-200);
    }).catch(() => {}).finally(() => {
      if (generation !== this.generation) return;
      this.busy = false;
      this.tick();
    });
  }
  clear() {
    this.generation++;
    this.pending = [];
    this.busy = false;
    this.speaker.cancel();
  }
}

export function recoveryLine(action: string, language: Language): string | undefined {
  const copy = {
    en: { agent_down: "Tactics agent down. Covering with templates.", caught_up: "Tactics is back." },
    es: { agent_down: "El agente Tactics se ha detenido. Seguimos con plantillas.", caught_up: "Tactics está de vuelta." },
    fr: { agent_down: "L’agent Tactics est arrêté. Les modèles prennent le relais.", caught_up: "Tactics est de retour." },
  };
  return copy[language][action as "agent_down" | "caught_up"];
}

export function useVoice({ enabled, cues, events, clock, speaker, language, speed, traces, session, kill }: {
  enabled: boolean;
  cues: OverlayCue[];
  events: MatchEvent[];
  clock: number;
  speaker?: Speaker;
  language: Language;
  speed: number;
  traces: Trace[];
  session: string;
  kill?: string;
}) {
  const queue = useRef<CommentaryQueue | undefined>(undefined);
  const seen = useRef(new Set<string>());
  const recovery = useRef(new Set<string>());
  useEffect(() => {
    seen.current.clear();
    recovery.current.clear();
    if (!enabled || !speaker) return;
    const current = new CommentaryQueue(speaker, () => performance.now());
    queue.current = current;
    if (import.meta.env.DEV || import.meta.env.MODE === "test")
      window.__playmakersCommentary = current.stats;
    const timer = setInterval(() => current.tick(), 250);
    return () => {
      clearInterval(timer);
      current.clear();
      queue.current = undefined;
    };
  }, [enabled, speaker, language, session]);
  useEffect(() => {
    const current = queue.current;
    if (!enabled || !current) return;
    current.setSpeed(speed);
    const announce = (action: string) => {
      const id = `${kill}:${action}`;
      const text = recoveryLine(action, language);
      if (!text || recovery.current.has(id)) return;
      recovery.current.add(id);
      current.enqueue({ id, text, language, priority: "key", emphasis: "big" });
    };
    if (kill) announce("agent_down");
    for (const trace of traces) {
      if (trace.agent === "tactics") announce(trace.action);
    }
    for (const cue of cues) {
      if (cue.persona !== "casual" || (cue.language ?? "en") !== language ||
        cue.clock_ms > clock || seen.current.has(cue.cue_id)) continue;
      seen.current.add(cue.cue_id);
      const moment = priorityMoment(cue, events);
      // Skip historical routine captions when enabling midway through a match.
      if (!moment && clock - cue.clock_ms > 8000 * speed) continue;
      const text = spokenLine(cue, events);
      if (!text) continue;
      current.enqueue({ id: cue.cue_id, text, language,
        priority: moment ? "key" : "routine",
        emphasis: moment === "goal" ? "goal" : moment ? "big" : "normal" });
    }
    current.tick();
  }, [enabled, cues, events, clock, language, speed, traces, kill, speaker, session]);
}
