import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseStreamMessage } from "./parse";
import type { MatchEvent, OverlayCue } from "./stream";
import {
  AzureSpeaker,
  BrowserSpeaker,
  CommentaryQueue,
  recoveryLine,
  useVoice,
  chooseSpeaker,
  spokenLine,
  type Speaker,
  type CommentaryLine,
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
afterEach(() => vi.unstubAllGlobals());

describe("voice commentary", () => {
  it("builds the fan line in the selected language", () => {
    expect(
      spokenLine(
        cue({
          payload: {
            headline: "¡Gol de Okafor para Northbridge Rovers!",
            detail: "Qué definición. La grada se pone en pie.",
          },
        }),
        events,
      ),
    ).toBe(
      "¡Gol de Okafor para Northbridge Rovers! Qué definición. La grada se pone en pie.",
    );
  });
  it.each([
    [
      "en",
      "If Okafor's shot in the 1st minute had been saved: win chance 41 percent instead of 65 percent.",
    ],
    [
      "es",
      "Si el disparo de Okafor en el minuto 1 hubiera sido detenido: probabilidad de victoria 41 por ciento en vez de 65 por ciento.",
    ],
    [
      "fr",
      "Si le tir de Okafor à la 1re minute avait été arrêté : chances de victoire 41 pour cent au lieu de 65 pour cent.",
    ],
  ] as const)("reads the panel's named What-If line in %s", (language, expected) => {
    const goal = events[0];
    if (goal.event_type !== "goal") throw new Error("expected goal fixture");
    expect(
      spokenLine(
        cue({
          template: "what_if",
          language,
          payload: {
            scenario: "if the shot had been saved",
            moment: { player_id: goal.scorer_player_id, minute: 1 },
            win_team_id: goal.scoring_team_id,
            metrics: { win_prob_after: 0.65, win_prob_counterfactual: 0.41 },
          },
        }),
        events,
      ),
    ).toBe(expected);
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
    expect(url).toBe("http://api/speech/tts");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ text: "Goal", language: "en", emphasis: "normal" });
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });
});


const line = (id: string, key = false): CommentaryLine => ({
  id, text: id, language: "en", priority: key ? "key" : "routine",
  emphasis: key ? "goal" : "normal",
});
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function fixture(max = 32) {
  let now = 0;
  const played: string[] = [];
  let finish: (() => void) | undefined;
  const speaker: Speaker = {
    name: "browser",
    speak: vi.fn((text: string) => new Promise<void>((resolve) => {
      played.push(text); finish = resolve;
    })),
    cancel: vi.fn(() => finish?.()),
  };
  const queue = new CommentaryQueue(speaker, () => now, 8000, max);
  return { queue, played, speaker, advance: (ms: number) => { now += ms; },
    finish: async () => { finish?.(); await flush(); } };
}
describe("full-match commentary queue", () => {
  it("puts key moments before pending routine captions and drops stale routines only", async () => {
    const f = fixture();
    f.queue.enqueue(line("opening")); f.queue.tick();
    f.queue.enqueue(line("routine")); f.queue.enqueue(line("goal", true));
    f.advance(9000); await f.finish();
    expect(f.played).toEqual(["opening", "goal"]);
    await f.finish();
    expect(f.queue.stats).toMatchObject({ spoken: 2, dropped: 1 });
  });
  it("bounds the queue, dropping oldest routines first and preserving key-only bursts", async () => {
    const f = fixture(2);
    f.queue.enqueue(line("old")); f.queue.enqueue(line("new"));
    f.queue.enqueue(line("goal", true));
    expect(f.queue.length).toBe(2);
    f.queue.tick(); await f.finish(); await f.finish();
    expect(f.played).toEqual(["goal", "new"]);
    expect(f.queue.stats.dropped).toBe(1);
    for (let i = 0; i < 4; i++) f.queue.enqueue(line(`key${i}`, true));
    expect(f.queue.length).toBe(2);
    f.queue.tick(); await f.finish(); await f.finish();
    expect(f.queue.stats.spoken).toBe(6);
  });
  it("clears pending and active speech without resurrecting it on completion", async () => {
    const f = fixture();
    f.queue.enqueue(line("active")); f.queue.tick();
    f.queue.enqueue(line("pending", true)); f.queue.clear();
    await flush();
    expect(f.speaker.cancel).toHaveBeenCalledOnce();
    expect(f.queue.length).toBe(0);
    expect(f.queue.stats.spoken).toBe(0);
    expect(f.played).toEqual(["active"]);
  });
  it.each(["en", "es", "fr"] as const)("queues localized recovery as key lines in %s", async (language) => {
    const f = fixture(); f.queue.setSpeed(50);
    for (const action of ["agent_down", "caught_up"]) {
      f.queue.enqueue({ ...line(action, true), text: recoveryLine(action, language)!, language });
    }
    f.queue.tick(); await f.finish(); await f.finish();
    expect(f.played).toEqual([recoveryLine("agent_down", language), recoveryLine("caught_up", language)]);
    expect(f.queue.stats).toMatchObject({ spoken: 2, dropped: 0 });
  });
  it("reports spoken vs dropped for a seed-like stream at 10x and 50x", async () => {
    for (const speed of [10, 50]) {
      const f = fixture(); f.queue.setSpeed(speed);
      for (let i = 0; i < 60; i++) {
        f.advance(30000 / speed);
        f.queue.enqueue(line(`event${i}`, i % 10 === 0));
        f.queue.tick(); await f.finish();
      }
      const expected = speed === 10 ? { spoken: 60, dropped: 0 } : { spoken: 6, dropped: 54 };
      console.info(`${speed}x commentary`, f.queue.stats.spoken, "spoken", f.queue.stats.dropped, "dropped");
      expect(f.queue.stats).toMatchObject(expected);
      expect(f.played.filter((text) => Number(text.slice(5)) % 10 === 0)).toHaveLength(6);
    }
  });
  it("discards queued routine captions when speed changes to 50x", () => {
    const f = fixture(); f.queue.enqueue(line("routine")); f.queue.enqueue(line("key", true));
    f.queue.setSpeed(50); f.queue.tick();
    expect(f.played).toEqual(["key"]); expect(f.queue.stats.dropped).toBe(1);
  });
  it.each([429, 503, 502])("falls back for the entire session after HTTP %s", async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("unavailable", { status }));
    vi.stubGlobal("fetch", fetchMock);
    const fallback: Speaker = { name: "browser", speak: vi.fn().mockResolvedValue(undefined), cancel: vi.fn() };
    const speaker = new AzureSpeaker("http://api", fallback);
    await speaker.speak("Goal", "en", "goal"); await speaker.speak("Next", "fr", "normal");
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fallback.speak).toHaveBeenNthCalledWith(1, "Goal", "en", "goal");
    expect(fallback.speak).toHaveBeenNthCalledWith(2, "Next", "fr", "normal");
  });
});


it("reads only the selected fan language, deduplicates recovery, and cancels on language/off changes", async () => {
  const f = fixture();
  const base: Parameters<typeof useVoice>[0] = {
    enabled: true, cues: [cue({ cue_id: "p1:tactics:fan", language: "en" }), cue({ cue_id: "p1:tactics:fr", language: "fr" })],
    events, clock: 1000, speaker: f.speaker, language: "en" as const, speed: 10,
    traces: [], session: "match7", kill: undefined as string | undefined,
  };
  const { rerender, unmount } = renderHook((props: Parameters<typeof useVoice>[0]) => useVoice(props), { initialProps: base });
  expect(f.speaker.speak).toHaveBeenCalledWith(spokenLine(base.cues[0], events), "en", "normal");
  await act(async () => { await f.finish(); });
  rerender({ ...base, kill: "tactics@1" });
  expect(f.speaker.speak).toHaveBeenCalledWith(recoveryLine("agent_down", "en"), "en", "big");
  await act(async () => { await f.finish(); });
  const calls = vi.mocked(f.speaker.speak).mock.calls.length;
  rerender({ ...base, kill: "tactics@1", cues: [...base.cues] });
  expect(f.speaker.speak).toHaveBeenCalledTimes(calls);
  rerender({ ...base, language: "fr" });
  expect(f.speaker.cancel).toHaveBeenCalledOnce();
  expect(f.speaker.speak).toHaveBeenLastCalledWith(spokenLine(base.cues[1], events), "fr", "normal");
  rerender({ ...base, enabled: false, language: "fr" });
  expect(f.speaker.cancel).toHaveBeenCalledTimes(2);
  unmount();
});


describe("speech-only commentator copy", () => {
  it.each([
    ["en", "Favourite: ★ GOAL, Marin 2'", "Northbridge Rovers lead 1-0.", "Goal! Marin scores in the 2nd minute. Northbridge Rovers lead 1-0."],
    ["fr", "Favori: ★ BUT, Marin 2'", "Northbridge Rovers mène 1-0.", "But ! Marin marque à la 2e minute. Northbridge Rovers mène 1-0."],
    ["es", "Favorito: ★ GOL, Marin 2'", "Northbridge Rovers gana 1-0.", "¡Gol! Marin marca en el minuto 2. Northbridge Rovers gana 1-0."],
  ] as const)("naturalizes goals in %s without mutating captions", (language, headline, detail, expected) => {
    const caption = cue({ language, payload: { headline, detail } });
    expect(spokenLine(caption, events)).toBe(expected);
    expect(caption.payload).toEqual({ headline, detail });
  });
  it.each([[1, "1st"], [2, "2nd"], [3, "3rd"], [11, "11th"], [12, "12th"], [13, "13th"], [21, "21st"]])(
    "speaks minute %s with the right ordinal", (minute, ordinal) => {
      expect(spokenLine(cue({ language: "en", payload: { headline: `Chance ${minute}′` } }), []))
        .toBe(`Chance in the ${ordinal} minute`);
    });
});

it("deduplicates cue updates and identical text while pending, active and recently spoken", async () => {
  const f = fixture();
  const kickoff = { ...line("kickoff"), text: "Kickoff for Northbridge Rovers." };
  f.queue.enqueue(kickoff);
  f.queue.enqueue({ ...kickoff, text: "An updated kickoff." });
  f.queue.enqueue({ ...kickoff, id: "other-writer" });
  expect(f.queue.length).toBe(1);
  f.queue.tick();
  f.queue.enqueue({ ...kickoff, id: "active-duplicate" });
  await f.finish();
  f.advance(9000);
  f.queue.enqueue({ ...kickoff, id: "recent-duplicate" });
  f.queue.tick();
  expect(f.played).toEqual([kickoff.text]);
  f.advance(1001);
  f.queue.enqueue({ ...kickoff, text: "Updated again." });
  f.queue.enqueue({ ...kickoff, id: "later" });
  f.queue.tick();
  expect(f.played).toEqual([kickoff.text, kickoff.text]);
  await f.finish();
  f.queue.clear();
  f.queue.enqueue(kickoff); f.queue.tick();
  expect(f.played).toHaveLength(3);
});
