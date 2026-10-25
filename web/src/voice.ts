import { useEffect, useRef } from "react";
import { recapText } from "./recapText";
import type { MatchEvent, OverlayCue, Trace } from "./stream";
import { whatIfQuestion } from "./whatifCopy";

export type Language = "en" | "es" | "fr";
export type Emphasis = "normal" | "goal" | "big";
export interface PreparedSpeech {
  readonly durationMs: number;
  play(): Promise<void>;
  dispose(): void;
}
export interface Speaker {
  readonly name: "browser" | "azure";
  readonly routineIntervalMs?: number;
  prepare?(text: string, language: Language, emphasis?: Emphasis): Promise<PreparedSpeech>;
  speak(text: string, language: Language, emphasis?: Emphasis, priority?: "key" | "routine"): Promise<void>;
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

export class SpeechBusy extends Error {}

export class AzureSpeaker implements Speaker {
  get name(): "azure" | "browser" { return this.failed ? "browser" : "azure"; }
  get routineIntervalMs() { return Math.ceil(60000 / this.perMinute / 100) * 100; }
  private generation = 0;
  private failed = false;
  private controllers = new Set<AbortController>();
  private clips = new Set<PreparedSpeech>();
  constructor(private readonly apiBase: string, private readonly fallback: Speaker = new BrowserSpeaker(),
    private readonly perMinute = 18) {}
  async prepare(text: string, language: Language, emphasis: Emphasis = "normal"): Promise<PreparedSpeech> {
    const fallbackClip = (): PreparedSpeech => ({
      durationMs: (text.length / 14.5 + .3) * 1000,
      play: () => this.fallback.speak(text, language, emphasis), dispose() {},
    });
    if (this.failed) return fallbackClip();
    const generation = this.generation;
    const controller = new AbortController();
    this.controllers.add(controller);
    try {
      const response = await fetch(`${this.apiBase}/speech/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, language, emphasis }),
        signal: controller.signal,
      });
      if (response.status === 429) {
        const body: unknown = await response.json().catch(() => null);
        const dailyCap = typeof body === "object" && body !== null && "detail" in body &&
          typeof body.detail === "string" && body.detail.startsWith("Daily speech character cap");
        // Both the shared Azure bucket and the per-client limiter are temporary.
        if (!dailyCap) throw new SpeechBusy("busy");
      }
      if (!response.ok) throw new Error(`Speech failed: ${response.status}`);
      const blob = await response.blob();
      if (generation !== this.generation) throw new DOMException("Cancelled", "AbortError");
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      let finish: (() => void) | undefined;
      let disposed = false;
      const clip: PreparedSpeech = {
        get durationMs() {
          return Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration * 1000 :
            (text.length / 14.5 + .3) * 1000;
        },
        play: () => new Promise<void>((resolve, reject) => {
          if (disposed) return resolve();
          finish = resolve;
          audio.onended = () => resolve();
          audio.onerror = () => reject(new Error("Audio failed"));
          void audio.play().catch(reject);
        }).catch(async () => {
          if (generation !== this.generation) return;
          this.failed = true;
          await this.fallback.speak(text, language, emphasis);
        }),
        dispose: () => {
          if (disposed) return;
          disposed = true;
          audio.pause();
          finish?.();
          URL.revokeObjectURL(url);
          this.clips.delete(clip);
        },
      };
      this.clips.add(clip);
      return clip;
    } catch (error) {
      if (error instanceof SpeechBusy || generation !== this.generation) throw error;
      this.failed = true;
      return fallbackClip();
    } finally {
      this.controllers.delete(controller);
    }
  }
  async speak(text: string, language: Language, emphasis: Emphasis = "normal") {
    const clip = await this.prepare(text, language, emphasis);
    try { await clip.play(); } finally { clip.dispose(); }
  }
  cancel() {
    this.generation++;
    for (const controller of this.controllers) controller.abort();
    for (const clip of this.clips) clip.dispose();
    this.fallback.cancel();
  }
}

export async function chooseSpeaker(apiBase: string): Promise<Speaker> {
  try {
    const response = await fetch(`${apiBase}/speech/config`);
    const config: unknown = await response.json();
    if (response.ok && typeof config === "object" && config !== null &&
      "azure" in config && config.azure === true) {
      const rate = "azure_per_minute" in config ? config.azure_per_minute : 18;
      return new AzureSpeaker(apiBase, new BrowserSpeaker(),
        typeof rate === "number" && Number.isFinite(rate) && rate > 0 ? rate : 18);
    }
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

function minutePhrase(minute: string, language: Language): string {
  if (language === "fr") return `à la ${minute}${minute === "1" ? "re" : "e"} minute`;
  if (language === "es") return `en el minuto ${minute}`;
  const n = Number(minute);
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? "th" :
    ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th");
  return `in the ${minute}${suffix} minute`;
}

/** Speech-only copy: keep the broadcast captions untouched. */
function commentaryText(text: string, language: Language): string {
  text = text.replace(/(?:Favourite|Favorito|Favori):\s*/gi, "").replace(/[★☆]/g, "").trim();
  text = text.replace(/^(?:GOAL|BUT|GOL),\s*(.+?)\s+(\d+)[’'′]/i, (_, player: string, minute: string) => {
    const opening = { en: `Goal! ${player} scores`, fr: `But ! ${player} marque`, es: `¡Gol! ${player} marca` }[language];
    return `${opening} ${minutePhrase(minute, language)}.`;
  });
  if (language === "en") text = text.replace(/(\d+)[’'′] (shot|chance|red card)/g,
    (_, minute: string, action: string) => `${action} ${minutePhrase(minute, language)}`);
  text = text.replace(/(?:à la |en el )?(\d+)[’'′]/g,
    (_, minute: string) => minutePhrase(minute, language));
  const percent = { en: "percent", es: "por ciento", fr: "pour cent" }[language];
  return text.replace(/%/g, ` ${percent}`).replace(/→/g, ", ")
    .replace(/\s+/g, " ").trim();
}

export function spokenLine(cue: OverlayCue, events: MatchEvent[]): string {
  const moment = priorityMoment(cue, events);
  const text = moment === "recap" ? recapText(cue).split("\n").join(" ") :
    moment === "what_if" ? whatIfQuestion(cue) :
    `${String(cue.payload.headline ?? "")} ${String(cue.payload.detail ?? "")}`.trim();
  return commentaryText(text, cue.language ?? "en");
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
  private seenIds = new Set<string>();
  private recentText = new Map<string, number>();
  private busy = false;
  private activeTextKey?: string;
  private generation = 0;
  private speed = 10;
  private lastRoutineAt = -Infinity;
  private fetching = false;
  private ready?: { line: Pending; clip: PreparedSpeech };
  private activeUntil = 0;
  private retryAt = 0;
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
    const now = this.now();
    for (const [text, at] of this.recentText) {
      if (now - at >= 10_000) this.recentText.delete(text);
    }
    const textKey = `${line.language}:${line.text.trim().replace(/\s+/g, " ")}`;
    if (this.seenIds.has(line.id) || this.recentText.has(textKey) || this.activeTextKey === textKey ||
      this.pending.some((pending) => pending.language === line.language && pending.text === line.text)) {
      this.seenIds.add(line.id);
      this.stats.dropped++;
      return;
    }
    this.seenIds.add(line.id);
    this.recentText.set(textKey, now);
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
  private nextBatch(): Pending | undefined {
    const key = this.pending.findIndex((line) => line.priority === "key");
    if (key >= 0) return this.pending.splice(key, 1)[0];
    if (this.speaker.name !== "azure") return this.pending.shift();
    // Take up to three freshest captions, in event order. Do not read the FIFO backlog.
    const selected: Pending[] = [];
    let chars = 0;
    while (this.pending.length && selected.length < 3 && chars < 48) {
      const next = this.pending.pop()!;
      const length = next.text.length + (/[.!?]$/.test(next.text) ? 0 : 1);
      if (selected.length && chars + length + 1 > 68) {
        this.stats.dropped += next.count;
        break;
      }
      selected.unshift(next);
      chars += length + (selected.length > 1 ? 1 : 0);
    }
    if (!selected.length) return;
    this.stats.dropped += this.pending.reduce((sum, line) => sum + line.count, 0);
    this.pending = [];
    const latest = selected[selected.length - 1];
    // Join complete captions, preserving names and facts. A single long caption stays intact.
    const text = selected.map(line => /[.!?]$/.test(line.text) ? line.text : `${line.text}.`).join(" ");
    return { ...latest, text, at: selected[0].at,
      count: selected.reduce((sum, line) => sum + line.count, 0) };
  }
  private tickPrepared() {
    if (this.ready && (this.ready.line.priority === "routine" &&
      (this.speed >= 50 || this.now() - this.ready.line.at > this.staleMs ||
        this.pending.some(line => line.priority === "key")))) {
      this.stats.dropped += this.ready.line.count;
      this.ready.clip.dispose();
      this.ready = undefined;
    }
    if (!this.busy && this.ready) {
      const { line, clip } = this.ready;
      this.ready = undefined;
      this.busy = true;
      this.activeUntil = this.now() + clip.durationMs;
      this.activeTextKey = `${line.language}:${line.text}`;
      const generation = this.generation;
      void clip.play().then(() => {
        if (generation !== this.generation) return;
        this.stats.spoken += line.count;
        this.stats.log = [...this.stats.log, line.text].slice(-200);
      }).finally(() => {
        clip.dispose();
        if (generation !== this.generation) return;
        this.activeTextKey = undefined;
        this.busy = false;
        this.tick();
      });
    }
    if (this.fetching || this.ready || this.now() < this.retryAt) return;
    // Request shortly before the current clip ends: overlap latency, retain fresh play-by-play.
    if (this.busy && this.now() < this.activeUntil - 1000) return;
    const key = this.pending.some(line => line.priority === "key");
    if (!key && this.speaker.name === "azure" &&
      this.now() - this.lastRoutineAt < (this.speaker.routineIntervalMs ?? 3400)) return;
    const line = this.nextBatch();
    if (!line) return;
    this.lastRoutineAt = this.now();
    this.fetching = true;
    const generation = this.generation;
    void this.speaker.prepare!(line.text, line.language, line.emphasis).then(clip => {
      if (generation !== this.generation) { clip.dispose(); return; }
      this.ready = { line, clip };
    }).catch((error: unknown) => {
      if (generation !== this.generation) return;
      if (error instanceof SpeechBusy) {
        // Rebuild from fresh arrivals on retry; key moments retain their place.
        this.pending.unshift(line);
        this.retryAt = this.now() + (this.speaker.routineIntervalMs ?? 3400);
      }
    }).finally(() => {
      if (generation !== this.generation) return;
      this.fetching = false;
      this.tick();
    });
  }
  tick() {
    this.prune();
    if (this.speaker.prepare) { this.tickPrepared(); return; }
    if (this.busy) return;
    const key = this.pending.findIndex((l) => l.priority === "key");
    if (key < 0 && this.speaker.name === "azure" &&
      this.now() - this.lastRoutineAt < (this.speaker.routineIntervalMs ?? 3400)) return;
    const line = this.pending.splice(key < 0 ? 0 : key, 1)[0];
    if (!line) return;
    if (line.priority === "routine" && this.speaker.name === "azure") this.lastRoutineAt = this.now();
    this.busy = true;
    this.activeTextKey = `${line.language}:${line.text.trim().replace(/\s+/g, " ")}`;
    const generation = this.generation;
    void this.speaker.speak(line.text, line.language, line.emphasis, line.priority).then(() => {
      if (generation !== this.generation) return;
      this.stats.spoken += line.count;
      this.stats.log.push(line.text);
      this.stats.log = this.stats.log.slice(-200);
    }).catch((error: unknown) => {
      if (generation === this.generation && error instanceof SpeechBusy) this.stats.dropped += line.count;
    }).finally(() => {
      if (generation !== this.generation) return;
      if (this.activeTextKey) this.recentText.set(this.activeTextKey, this.now());
      this.activeTextKey = undefined;
      this.busy = false;
      this.tick();
    });
  }
  clear() {
    this.generation++;
    this.pending = [];
    this.ready?.clip.dispose();
    this.ready = undefined;
    this.fetching = false;
    this.retryAt = 0;
    this.lastRoutineAt = -Infinity;
    this.seenIds.clear();
    this.recentText.clear();
    this.activeTextKey = undefined;
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
