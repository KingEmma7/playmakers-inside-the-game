import { afterEach, describe, expect, it, vi } from "vitest";
import { parseStreamMessage } from "./parse";
import type { MatchEvent, OverlayCue } from "./stream";
import {
  AzureSpeaker,
  BrowserSpeaker,
  MIN_GAP_MS,
  chooseSpeaker,
  shouldSpeak,
  spokenLine,
  type VoiceState,
} from "./voice";

const event = (fields: Record<string, unknown>): MatchEvent => {
  const message = parseStreamMessage(
    JSON.stringify({
      type: "event",
      schema_version: "1.0.0",
      match_id: "match_7",
      clock_ms: 0,
      period: 1,
      labels: [],
      ...fields,
    }),
  );
  if (message.kind !== "event") throw new Error("bad fixture");
  return message.event;
};
const events = [
  event({
    event_id: "match_7:000001",
    sequence: 1,
    event_type: "goal",
    scoring_team_id: "match_7_HOME",
    scorer_player_id: "match_7_H09",
    shot_event_id: "s1",
  }),
  event({ event_id: "p1", sequence: 2, event_type: "pass" }),
];
const cue = (overrides: Partial<OverlayCue>): OverlayCue => ({
  cue_id: "match_7:000001:storyline:viewer1",
  clock_ms: 1000,
  template: "storyline",
  payload: {
    headline: "¡Llega el próximo ataque!",
    detail: "Sigue la emoción del partido.",
  },
  evidence_event_ids: ["match_7:000001"],
  persona: "casual",
  language: "es",
  ...overrides,
});
const fresh = (): VoiceState => ({
  lastAt: -Infinity,
  speaking: false,
  spoken: new Set(),
});

afterEach(() => vi.unstubAllGlobals());

describe("voice commentary", () => {
  it("speaks only priority moments, spaced out, never twice and never stale", () => {
    const state = fresh();
    const goal = cue({});
    expect(
      shouldSpeak(
        cue({ cue_id: "p1:tactics:viewer1" }),
        events,
        1000,
        0,
        state,
      ),
    ).toBe(false);
    expect(shouldSpeak(goal, events, 1000, 0, state)).toBe(true);
    expect(shouldSpeak(goal, events, 7000, 0, state)).toBe(false);
    state.spoken.add(goal.cue_id);
    state.lastAt = 0;
    expect(shouldSpeak(goal, events, 1000, MIN_GAP_MS, state)).toBe(false);
    const whatif = cue({
      cue_id: "match_7:000001:what_if:viewer1",
      template: "what_if",
    });
    expect(shouldSpeak(whatif, events, 1000, MIN_GAP_MS - 1, state)).toBe(
      false,
    );
    expect(shouldSpeak(whatif, events, 1000, MIN_GAP_MS, state)).toBe(true);
    expect(
      shouldSpeak({ ...whatif, cue_id: "x" }, events, 1000, MIN_GAP_MS, {
        ...state,
        speaking: true,
      }),
    ).toBe(false);
    const recap = cue({ cue_id: "ft:recap:viewer1", template: "recap" });
    expect(
      shouldSpeak(recap, events, 1000, 1, { ...state, speaking: true }),
    ).toBe(true);
  });
  it("builds the fan line in the selected language", () => {
    expect(spokenLine(cue({}), events)).toBe(
      "¡Gol de Northbridge Rovers! ¡Llega el próximo ataque! Sigue la emoción del partido.",
    );
    expect(
      spokenLine(
        cue({
          template: "what_if",
          payload: { scenario: "if the shot had been saved" },
        }),
        events,
      ),
    ).toBe("¿Y si ese disparo se hubiera detenido?");
  });
  it("uses the browser voice for the chosen locale", async () => {
    const spoken: { text: string; lang: string }[] = [];
    class Utterance {
      lang = "";
      onend?: () => void;
      constructor(readonly text: string) {}
    }
    vi.stubGlobal("SpeechSynthesisUtterance", Utterance);
    vi.stubGlobal("speechSynthesis", {
      speak: (u: Utterance) => {
        spoken.push({ text: u.text, lang: u.lang });
        u.onend?.();
      },
      cancel: vi.fn(),
    });
    await new BrowserSpeaker().speak("But !", "fr");
    expect(spoken).toEqual([{ text: "But !", lang: "fr-FR" }]);
  });
  it("chooses Azure only when the API reports it configured, keyless from the browser", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect((await chooseSpeaker("http://api")).name).toBe("browser");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ azure: true, region: "westeurope" })),
      )
      .mockResolvedValueOnce(new Response(new Blob(["mp3"])));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: () => "blob:x",
        revokeObjectURL: vi.fn(),
      }),
    );
    class FakeAudio {
      onended?: () => void;
      play() {
        this.onended?.();
        return Promise.resolve();
      }
      pause() {}
    }
    vi.stubGlobal("Audio", FakeAudio);
    const speaker = await chooseSpeaker("http://api");
    expect(speaker).toBeInstanceOf(AzureSpeaker);
    await speaker.speak("Goal", "en");
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("http://api/speech/synthesize?text=Goal&language=en");
    expect(init.headers).toEqual({ "X-Playmakers-Speech": "1" });
  });
});
