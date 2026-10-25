// Frozen pre-fix queue for the deterministic timeline comparison.
import { SpeechBusy, type Speaker, type CommentaryLine } from "../voice";
type Pending = CommentaryLine & { at: number; count: number };
export type CommentaryDebug = { spoken: number; dropped: number; log: string[] };

/** Pure scheduling: callers supply the wall clock, speaker, arrivals and ticks. */
export class BaselineCommentaryQueue {
  readonly stats: CommentaryDebug = { spoken: 0, dropped: 0, log: [] };
  private pending: Pending[] = [];
  private seenIds = new Set<string>();
  private recentText = new Map<string, number>();
  private busy = false;
  private activeTextKey?: string;
  private generation = 0;
  private speed = 10;
  private lastRoutineAt = -Infinity;
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
  tick() {
    this.prune();
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
    this.seenIds.clear();
    this.recentText.clear();
    this.activeTextKey = undefined;
    this.busy = false;
    this.speaker.cancel();
  }
}
