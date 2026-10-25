import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseStreamMessage } from "./parse";
import type { MatchEvent, OverlayCue } from "./stream";
import {
  AzureSpeaker,
  BrowserSpeaker,
  SpeechBusy,
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
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

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
        new Response(JSON.stringify({ azure: true, region: "westeurope", azure_per_minute: 12 })),
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
    expect(speaker.routineIntervalMs).toBe(5000);
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
  it.each([503, 502])("falls back for the entire session after HTTP %s", async (status) => {
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
  expect(f.speaker.speak).toHaveBeenCalledWith(spokenLine(base.cues[0], events), "en", "normal", "routine");
  await act(async () => { await f.finish(); });
  rerender({ ...base, kill: "tactics@1" });
  expect(f.speaker.speak).toHaveBeenCalledWith(recoveryLine("agent_down", "en"), "en", "big", "key");
  await act(async () => { await f.finish(); });
  const calls = vi.mocked(f.speaker.speak).mock.calls.length;
  rerender({ ...base, kill: "tactics@1", cues: [...base.cues] });
  expect(f.speaker.speak).toHaveBeenCalledTimes(calls);
  rerender({ ...base, language: "fr" });
  expect(f.speaker.cancel).toHaveBeenCalledOnce();
  expect(f.speaker.speak).toHaveBeenLastCalledWith(spokenLine(base.cues[1], events), "fr", "normal", "routine");
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


describe("Azure rate pressure", () => {
  it("paces routine starts, lets key lines bypass pacing, and leaves browser unpaced", async () => {
    let now = 0;
    let browser = false;
    const speaker: Speaker = {
      get name() { return browser ? "browser" : "azure"; },
      routineIntervalMs: 5000,
      speak: vi.fn().mockResolvedValue(undefined), cancel: vi.fn(),
    };
    const queue = new CommentaryQueue(speaker, () => now);
    queue.enqueue(line("first")); queue.tick(); await flush();
    queue.enqueue(line("second")); queue.tick(); await flush();
    expect(speaker.speak).toHaveBeenCalledTimes(1);
    queue.enqueue(line("key", true)); queue.tick(); await flush();
    expect(speaker.speak).toHaveBeenLastCalledWith("key", "en", "goal", "key");
    now = 4999; queue.tick(); await flush();
    expect(speaker.speak).toHaveBeenCalledTimes(2);
    now = 5000; queue.tick(); await flush();
    expect(speaker.speak).toHaveBeenLastCalledWith("second", "en", "normal", "routine");
    browser = true;
    queue.enqueue(line("browser")); queue.tick(); await flush();
    expect(speaker.speak).toHaveBeenCalledTimes(4);
  });

  it.each(["busy", "Too many speech requests; try again shortly"])(
    "retries transient %s on Azure for routine and key lines", async (detail) => {
      let now = 0;
      const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(
        new Response(JSON.stringify({ detail }), { status: 429 }),
      ));
      vi.stubGlobal("fetch", fetchMock);
      const fallback: Speaker = {
        name: "browser", speak: vi.fn().mockResolvedValue(undefined), cancel: vi.fn(),
      };
      const speaker = new AzureSpeaker("http://api", fallback);
      const queue = new CommentaryQueue(speaker, () => now);
      queue.enqueue(line("routine")); queue.tick(); await flush();
      expect(queue.stats).toMatchObject({ dropped: 0, spoken: 0 });
      expect(queue.length).toBe(1);
      queue.enqueue({ ...line("key", true), emphasis: "normal" });
      now = 3399; queue.tick(); await flush();
      expect(fetchMock).toHaveBeenCalledOnce();
      now = 3400; queue.tick(); await flush();
      expect(JSON.parse(fetchMock.mock.calls[1][1].body).text).toBe("key");
      expect(fallback.speak).not.toHaveBeenCalled();
      expect(speaker.name).toBe("azure");
      queue.clear();
    });

  it("uses browser for the session after the daily cap and removes pacing", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "Daily speech character cap reached; use browser commentary" }),
      { status: 429 },
    ));
    vi.stubGlobal("fetch", fetchMock);
    let finish: (() => void) | undefined;
    const fallback: Speaker = {
      name: "browser",
      speak: vi.fn(() => new Promise<void>((resolve) => { finish = resolve; })),
      cancel: vi.fn(),
    };
    const speaker = new AzureSpeaker("http://api", fallback);
    // Keep the queue clock fixed: the next routine must start without Azure pacing.
    const queue = new CommentaryQueue(speaker, () => 0);
    queue.enqueue(line("one")); queue.tick();
    // Drain async response parsing and promise continuations without counting microtasks.
    await vi.advanceTimersByTimeAsync(0);
    expect(speaker.name).toBe("browser");
    queue.enqueue(line("two"));
    expect(fallback.speak).toHaveBeenCalledExactlyOnceWith("one.", "en", "normal");
    expect(queue.stats.spoken).toBe(0);
    expect(queue.length).toBe(1);

    finish?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(fallback.speak).toHaveBeenCalledTimes(2);
    expect(fallback.speak).toHaveBeenLastCalledWith("two", "en", "normal");
    expect(queue.stats.spoken).toBe(1);
    expect(queue.length).toBe(0);

    finish?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(queue.stats.spoken).toBe(2);
    expect(queue.stats.log).toEqual(["one.", "two"]);
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});

function preparedFixture() {
  let now = 0;
  const requests: string[] = [], played: string[] = [];
  const releases: (() => void)[] = [];
  const disposals: string[] = [];
  const speaker: Speaker = {
    name: "azure", routineIntervalMs: 3400,
    speak: vi.fn(), cancel: vi.fn(),
    prepare: vi.fn(async (text) => {
      requests.push(text);
      return { durationMs: 4500,
        play: () => new Promise<void>(resolve => { played.push(text); releases.push(resolve); }),
        dispose: () => { disposals.push(text); },
      };
    }),
  };
  const queue = new CommentaryQueue(speaker, () => now);
  return { queue, speaker, requests, played, disposals,
    at: async (ms: number) => { now = ms; queue.tick(); await flush(); },
    finish: async () => { releases.shift()?.(); await flush(); },
  };
}

describe("Azure batches and prefetch", () => {
  it("joins at most three freshest whole captions in event order, dropping backlog", async () => {
    const f = preparedFixture();
    for (const text of ["Old backlog", "Still old", "Alba passes", "Kaito turns", "Marin runs"])
      f.queue.enqueue({ ...line(text), text });
    await f.at(0);
    expect(f.requests).toEqual(["Alba passes. Kaito turns. Marin runs."]);
    expect(f.queue.stats.dropped).toBe(2);
    await f.finish();
    expect(f.queue.stats.spoken).toBe(3);
  });
  it("fetches next audio while current plays and starts it immediately on completion", async () => {
    const f = preparedFixture();
    f.queue.enqueue(line("Opening play")); await f.at(0);
    f.queue.enqueue(line("Next play")); await f.at(3499);
    expect(f.requests).toHaveLength(1);
    await f.at(3500);
    expect(f.requests).toEqual(["Opening play.", "Next play."]);
    expect(f.played).toEqual(["Opening play."]);
    await f.at(4500); await f.finish();
    expect(f.played).toEqual(["Opening play.", "Next play."]);
    f.queue.clear();
  });
  it("discards stale prefetched routines and gives key moments priority", async () => {
    const f = preparedFixture();
    f.queue.enqueue(line("Opening")); await f.at(0);
    f.queue.enqueue(line("Old routine")); await f.at(3500);
    f.queue.enqueue(line("Goal!", true)); await f.at(3600);
    expect(f.disposals).toContain("Old routine.");
    await f.finish();
    expect(f.played).toEqual(["Opening.", "Goal!"]);
    f.queue.enqueue(line("Aging")); await f.at(7100);
    await f.at(16000); await f.finish();
    expect(f.played).not.toContain("Aging.");
    f.queue.clear();
  });
  it("retries busy with fresh play instead of the rejected backlog", async () => {
    const f = preparedFixture();
    vi.mocked(f.speaker.prepare!).mockRejectedValueOnce(new SpeechBusy());
    f.queue.enqueue(line("Old play")); await f.at(0);
    expect(f.queue.stats.dropped).toBe(0);
    await f.at(9000); f.queue.enqueue(line("Fresh play")); await f.at(9000);
    expect(f.requests).toEqual(["Fresh play."]);
    expect(f.played).toEqual(["Fresh play."]);
    expect(f.queue.stats.dropped).toBe(1);
    f.queue.clear();
  });
  it("disposes a late prefetch after cancellation without resurrecting playback", async () => {
    const f = preparedFixture();
    let release: ((clip: Awaited<ReturnType<NonNullable<Speaker["prepare"]>>>) => void) | undefined;
    vi.mocked(f.speaker.prepare!).mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    f.queue.enqueue(line("Opening")); f.queue.tick(); f.queue.clear();
    const clip = { durationMs: 4000, play: vi.fn(), dispose: vi.fn() };
    release?.(clip); await flush();
    expect(clip.dispose).toHaveBeenCalledOnce();
    expect(clip.play).not.toHaveBeenCalled();
  });
});

it("prepares real Azure audio without playing it and releases prefetched clips on cancel", async () => {
  const fallback: Speaker = { name: "browser", speak: vi.fn(), cancel: vi.fn() };
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(new Response(new Blob(["mp3"])))));
  const revoke = vi.fn(), play = vi.fn().mockResolvedValue(undefined), pause = vi.fn();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:prepared", revokeObjectURL: revoke }));
  class Audio {
    duration = 4;
    play = play;
    pause = pause;
  }
  vi.stubGlobal("Audio", Audio);
  const speaker = new AzureSpeaker("http://api", fallback);
  const first = await speaker.prepare("First play", "en");
  const next = await speaker.prepare("Next play", "en");
  expect(play).not.toHaveBeenCalled();
  expect(first.durationMs).toBe(4000);
  const playing = first.play();
  expect(play).toHaveBeenCalledOnce();
  speaker.cancel(); await playing;
  expect(pause).toHaveBeenCalledTimes(2);
  expect(revoke).toHaveBeenCalledTimes(2);
  next.dispose();
  expect(revoke).toHaveBeenCalledTimes(2);
  expect(fallback.speak).not.toHaveBeenCalled();
});
