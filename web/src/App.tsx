import { useEffect, useState } from "react";
import lockupUrl from "./assets/playmakers-lockup.svg";
import symbolUrl from "./assets/playmakers-symbol.svg";
import { ViewPanel, Crest } from "./Overlay";
import { countLabel, playerName } from "./players";
import TracePanel from "./TracePanel";
import { apiBaseUrl, usePlaymakersStream, clockLabel, type Stream } from "./stream";
import { chooseSpeaker, useVoice, type Speaker } from "./voice";
const FAN_LANGUAGES = ["en", "es", "fr"] as const;
type FanLanguage = (typeof FAN_LANGUAGES)[number];
function About() {
  return (
    <main className="about">
      <div className="about-copy">
        <img className="about-mark" src={symbolUrl} alt="" width={48} height={48} />
        <h1>
          One match.
          <br />
          A whole production crew.
        </h1>
        <p>
          Playmakers turns a seeded, synthetic football match into evidence-backed
          broadcast overlays and a personalised second screen. Every club,
          player and match is fictional.
        </p>
        <div className="architecture">
          <p>
            <b>Source</b> PitchSim synthetic events · Replay API
          </p>
          <p>
            <b>Production</b> Director · Stats MCP · Tactics · Storyline ·
            What-If
          </p>
          <p>
            <b>Delivery</b> Compliance · Graphics · Audience · Your screen
          </p>
        </div>
        <h2>Two AI writers. Rule-based checks around them.</h2>
        <p>
          A Microsoft Agent Framework workflow runs the crew. Tactics and
          Storyline write with a language model. Stats, Compliance, Graphics and
          Audience are deterministic: they serve numbers over MCP, check every
          claim against event IDs, validate cues and shape them for analysts and
          fans in English, Spanish or French.
        </p>
        <h2>Built to keep broadcasting.</h2>
        <p>
          Kill Tactics during a match: deterministic captions take over within
          one event. The agent reloads its checkpoint and catches up. What-If
          uses parallel, seeded PitchSim continuations to explain alternative
          outcomes.
        </p>
        <h2>What is running here?</h2>
        <p>
          Without Azure settings an offline mock model stands in, so agent
          timings are local, not model latency. With Microsoft Foundry or Azure
          OpenAI set, Tactics and Storyline are called only on key moments.
        </p>
        <p className="muted">
          Press D on Replay to toggle broadcast safe areas.
        </p>
        <p className="muted">
          Player motion is a formation-based visualisation around observed
          ball/action positions; it is not real tracking data. What-If
          probabilities are illustrative synthetic continuations.
        </p>
      </div>
    </main>
  );
}
export default function App() {
  return <Playmakers />;
}
function Playmakers() {
  const [seed, setSeed] = useState(382);
  const [showOnboarding, setShowOnboarding] = useState(
    () => sessionStorage.getItem("playmakers-onboarding-dismissed") !== "true",
  );
  const [speed, setSpeed] = useState(10);
  const [language, setLanguage] = useState<FanLanguage>("en");
  const [liveModel, setLiveModel] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBaseUrl()}/model/config`)
      .then((response) => response.json())
      .then((data: unknown) => {
        const live =
          typeof data === "object" && data !== null && "live" in data && data.live === true;
        if (!cancelled) setLiveModel(live);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  const [favourite, setFavourite] = useState("H09");
  const [safe, setSafe] = useState(false);
  const [running, setRunning] = useState(true);
  const [pausedSequence, setPausedSequence] = useState(-1);
  const [replayFrom, setReplayFrom] = useState(0);
  const [kill, setKill] = useState<string>();
  const [voice, setVoice] = useState(false);
  const [speaker, setSpeaker] = useState<Speaker>();
  const [about, setAbout] = useState(location.pathname === "/about");
  function navigate(path: string) {
    history.pushState(null, "", path);
    setAbout(path === "/about");
  }
  useEffect(() => {
    const back = () => setAbout(location.pathname === "/about");
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);
  useEffect(() => {
    const toggle = (e: KeyboardEvent) => {
      if (
        e.key.toLowerCase() === "d" &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLSelectElement)
      )
        setSafe((value) => !value);
    };
    window.addEventListener("keydown", toggle);
    return () => window.removeEventListener("keydown", toggle);
  }, []);
  const viewer_profiles = JSON.stringify([
    { persona: "analyst", language: "en" },
    { persona: "casual", language, favorite_player_id: favourite ? `match_${seed}_${favourite}` : null },
  ]);
  const analyst = usePlaymakersStream({
    seed,
    speed,
    persona: "analyst",
    language: "en",
    kill,
    replay_from_ms: replayFrom,
    whatif_rollouts: 200,
    viewer_profiles,
  });
  const fan = usePlaymakersStream({
    seed,
    speed,
    persona: "casual",
    language,
    favourite_player_id: favourite ? `match_${seed}_${favourite}` : undefined,
    kill,
    replay_from_ms: replayFrom,
    whatif_rollouts: 200,
    viewer_profiles,
  });
  // Failure injection rebuilds a deterministic prefix in a new shared session.
  // Keep the current event, pitch and cues until both feeds reach that prefix.
  const [held, setHeld] = useState<{
    analyst: Stream;
    fan: Stream;
    sequence: number;
  }>();
  const replaying = Boolean(
    held && Math.min(
      analyst.events.at(-1)?.sequence ?? -1,
      fan.events.at(-1)?.sequence ?? -1,
    ) < held.sequence,
  );
  const displayedAnalyst = replaying && held ? held.analyst : analyst;
  const displayedFan = replaying && held ? held.fan : fan;
  const shared = Math.min(
    displayedAnalyst.events.at(-1)?.sequence ?? -1,
    displayedFan.events.at(-1)?.sequence ?? -1,
  );
  const sequence = running ? shared : Math.min(pausedSequence, shared);
  const event = displayedAnalyst.events.find((e) => e.sequence === sequence);
  const clock = event?.clock_ms ?? 0;
  useVoice({
    enabled: voice && running && !replaying,
    cues: fan.cues,
    events: fan.events,
    clock,
    speaker,
  });
  const traces = [
    ...analyst.traces.filter((t) => t.sequence <= sequence),
    ...fan.traces.filter((t) => t.sequence <= sequence),
  ].sort((a, b) => a.sequence - b.sequence);
  function restart() {
    setHeld(undefined);
    setReplayFrom(0);
    setKill(undefined);
    setRunning(true);
  }
  return (
    <div className="app-shell">
      <header>
        <a className="brand" href="/" aria-label="Playmakers home">
          <img src={lockupUrl} alt="Playmakers" height={26} />
        </a>
        <nav className="segmented" aria-label="Main navigation">
          <a
            href="/"
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
            aria-current={!about ? "page" : undefined}
          >
            Replay
          </a>
          <a
            href="/about"
            onClick={(e) => {
              e.preventDefault();
              navigate("/about");
            }}
            aria-current={about ? "page" : undefined}
          >
            About
          </a>
        </nav>
        {!about && (
          <section className="toolbar" aria-label="Replay controls">
            <div className="control">
              <label htmlFor="seed">Seed</label>
              <input
                id="seed"
                aria-label="MATCH SEED"
                type="number"
                min="0"
                max="10000"
                value={seed}
                onChange={(e) => {
                  setSeed(
                    Math.max(0, Math.min(10000, Number(e.target.value))),
                  );
                  restart();
                }}
              />
            </div>
            <div className="control">
              <label htmlFor="speed">Speed</label>
              <select
                id="speed"
                aria-label="REPLAY SPEED"
                value={speed}
                onChange={(e) => {
                  setSpeed(Number(e.target.value));
                  restart();
                }}
              >
                {[1, 10, 50].map((n) => (
                  <option key={n} value={n}>
                    {n}×
                  </option>
                ))}
              </select>
            </div>
            <button
              className="play"
              onClick={() => {
                if (running) setPausedSequence(shared);
                setRunning(!running);
              }}
            >
              {running ? "Pause" : "Start"}
            </button>
            <span className="toolbar-divider" />
            <div className="control">
              <label htmlFor="language">Language</label>
              <select
                id="language"
                aria-label="FAN LANGUAGE"
                value={language}
                onChange={(e) => {
                  const choice = FAN_LANGUAGES.find((l) => l === e.target.value);
                  if (choice) setLanguage(choice);
                }}
              >
                <option value="en">English</option>
                <option value="es">Español</option>
                <option value="fr">Français</option>
              </select>
            </div>
            <button
              type="button"
              className="control voice-toggle"
              aria-pressed={voice}
              onClick={() => {
                if (!speaker) void chooseSpeaker(apiBaseUrl()).then(setSpeaker);
                setVoice(!voice);
              }}
            >
              <span>Voice</span> <b>{voice ? "On" : "Off"}</b>
            </button>
            <div className="control favourite-control">
              <label htmlFor="favourite">Following</label>
              <select
                id="favourite"
                aria-label="FAVOURITE PLAYER"
                value={favourite}
                onChange={(e) => setFavourite(e.target.value)}
              >
                <option value="">No favourite</option>
                {["H", "A"].flatMap((team) =>
                  Array.from({ length: 11 }, (_, i) => {
                    const id = `${team}${String(i + 1).padStart(2, "0")}`;
                    return (
                      <option key={id} value={id}>
                        {playerName(id)}
                      </option>
                    );
                  }),
                )}
              </select>
            </div>
            {(analyst.offline || fan.offline) && (
              <span
                className="control offline-demo"
                role="status"
                title="The live model is at its limit right now, so this match runs on the offline crew. Every insight is still verified."
              >
                Offline demo
              </span>
            )}
          </section>
        )}
      </header>
      {about ? (
        <About />
      ) : (
        <>
          <div className="hero">
            <span>Northbridge Rovers</span>
            <Crest />
            <strong>
              {
                displayedAnalyst.events.filter(
                  (e) =>
                    e.sequence <= sequence &&
                    e.event_type === "goal" &&
                    e.scoring_team_id.endsWith("_HOME"),
                ).length
              }
            </strong>
            <div>
              <time className="shared-clock">{clockLabel(clock)}</time>
              <small>
                {event?.period === 2 ? "Second half" : "First half"}
              </small>
            </div>
            <strong>
              {
                displayedAnalyst.events.filter(
                  (e) =>
                    e.sequence <= sequence &&
                    e.event_type === "goal" &&
                    !e.scoring_team_id.endsWith("_HOME"),
                ).length
              }
            </strong>
            <Crest away />
            <span>Southport Athletic</span>
          </div>
          {showOnboarding && (
            <div className="onboarding" role="note">
              <span>
                8 AI and rule-based agents produce this fictional match live: one
                analyst feed, one fan feed, every claim checked against match
                events. Try Stop Tactics to see recovery.
              </span>
              <button
                type="button"
                aria-label="Dismiss introduction"
                onClick={() => {
                  sessionStorage.setItem("playmakers-onboarding-dismissed", "true");
                  setShowOnboarding(false);
                }}
              >
                ×
              </button>
            </div>
          )}
          <main className="playmakers-layout">
            <div className="program-area">
              <div className="split-view">
                <ViewPanel
                  title="Analyst"
                  persona="analyst"
                  event={event}
                  events={displayedAnalyst.events}
                  cues={displayedAnalyst.cues}
                  clock={clock}
                  safe={safe}
                  running={running && !replaying}
                  status={analyst.status}
                />
                <ViewPanel
                  title="For you"
                  persona="casual"
                  event={displayedFan.events.find((e) => e.sequence === sequence)}
                  events={displayedFan.events}
                  cues={displayedFan.cues}
                  clock={clock}
                  safe={safe}
                  running={running && !replaying}
                  status={fan.status}
                  favourite={favourite}
                  language={language}
                />
              </div>
            </div>
            <TracePanel
              traces={traces}
              key={`${seed}-${speed}-${kill ?? "normal"}-${replayFrom}-${language}`}
              killRequested={Boolean(kill)}
              mockModel={!liveModel || Boolean(analyst.offline || fan.offline)}
              disabled={!event || !running || replaying}
              onKill={() => {
                const minute = Math.floor(clock / 60000);
                setHeld({ analyst: displayedAnalyst, fan: displayedFan, sequence });
                setReplayFrom(clock);
                setKill(`tactics@${minute}`);
              }}
            />
          </main>
          <section className="timeline" aria-label="Match timeline">
            <div>
              <b>Match so far</b>
              <span>
                {countLabel(
                  displayedAnalyst.events.filter(
                    (e) => e.sequence <= sequence && e.event_type === "shot",
                  ).length,
                  "shot",
                )}{" "}
                · Synthetic match
              </span>
            </div>
            <div className="timeline-track">
              <i
                style={{ width: `${Math.min(100, (clock / 5400000) * 100)}%` }}
              />
              {displayedAnalyst.events
                .filter(
                  (e) =>
                    e.sequence <= sequence &&
                    ["goal", "shot", "card"].includes(e.event_type),
                )
                .map((e) => (
                  <span
                    key={e.event_id}
                    className={`timeline-event ${e.event_type}`}
                    style={{
                      left: `${Math.min(100, (e.clock_ms / 5400000) * 100)}%`,
                    }}
                    title={`${e.event_type} · ${clockLabel(e.clock_ms)}`}
                  />
                ))}
            </div>
            <div className="timeline-ticks">
              {[0, 15, 30, 45, 60, 75, 90].map((n) => (
                <span key={n}>{n}′</span>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
