import { useEffect, useState } from "react";
import lockupUrl from "./assets/playmakers-lockup.svg";
import symbolUrl from "./assets/playmakers-symbol.svg";
import { ViewPanel, Crest } from "./Overlay";
import { playerName } from "./players";
import TracePanel from "./TracePanel";
import { usePlaymakersStream, clockLabel } from "./stream";
const FAN_LANGUAGES = ["es", "fr"] as const;
type FanLanguage = (typeof FAN_LANGUAGES)[number];
function About() {
  return (
    <main className="about">
      <div className="about-copy">
        <img className="about-mark" src={symbolUrl} alt="" width={48} height={48} />
        <h1>
          One match.
          <br />
          An entire AI crew.
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
        <h2>A specialist crew. One verified story.</h2>
        <p>
          Microsoft Agent Framework coordinates specialist agents. Deterministic
          Stats tools provide numbers through MCP. Compliance checks claims
          against event IDs. Graphics validates timed cues, and Audience shapes
          the same moment for analysts and fans in English, Spanish or French.
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
          The local demo uses an offline mock model, in-memory state and file
          checkpoints. Foundry/Azure OpenAI model clients are available when
          configured. Cosmos DB, Container Apps deployment and cloud
          observability are planned for Phase 4; this page does not claim they
          are deployed.
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
  const [seed, setSeed] = useState(7);
  const [speed, setSpeed] = useState(10);
  const [language, setLanguage] = useState<FanLanguage>("es");
  const [favourite, setFavourite] = useState("H09");
  const [safe, setSafe] = useState(false);
  const [running, setRunning] = useState(true);
  const [pausedSequence, setPausedSequence] = useState(-1);
  const [replayFrom, setReplayFrom] = useState(0);
  const [kill, setKill] = useState<string>();
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
  const shared = Math.min(
    analyst.events.at(-1)?.sequence ?? -1,
    fan.events.at(-1)?.sequence ?? -1,
  );
  const sequence = running ? shared : Math.min(pausedSequence, shared);
  const event = analyst.events.find((e) => e.sequence === sequence);
  const clock = event?.clock_ms ?? 0;
  const traces = [
    ...analyst.traces.filter((t) => t.sequence <= sequence),
    ...fan.traces.filter((t) => t.sequence <= sequence),
  ].sort((a, b) => a.sequence - b.sequence);
  function restart() {
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
                <option value="es">Español</option>
                <option value="fr">Français</option>
              </select>
            </div>
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
                analyst.events.filter(
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
                analyst.events.filter(
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
          <main className="playmakers-layout">
            <div className="program-area">
              <div className="split-view">
                <ViewPanel
                  title="Analyst"
                  persona="analyst"
                  event={event}
                  events={analyst.events}
                  cues={analyst.cues}
                  clock={clock}
                  safe={safe}
                  running={running}
                  status={analyst.status}
                />
                <ViewPanel
                  title="For you"
                  persona="casual"
                  event={fan.events.find((e) => e.sequence === sequence)}
                  events={fan.events}
                  cues={fan.cues}
                  clock={clock}
                  safe={safe}
                  running={running}
                  status={fan.status}
                  favourite={favourite}
                />
              </div>
            </div>
            <TracePanel
              traces={traces}
              recoveryClock={replayFrom}
              disabled={!event || !running || Boolean(kill)}
              onKill={() => {
                const minute = Math.floor(clock / 60000);
                setReplayFrom(Math.floor(clock / 60000) * 60000);
                setKill(`tactics@${minute}`);
              }}
            />
          </main>
          <section className="timeline" aria-label="Match timeline">
            <div>
              <b>Match so far</b>
              <span>
                {
                  analyst.events.filter(
                    (e) => e.sequence <= sequence && e.event_type === "shot",
                  ).length
                }{" "}
                shots · Synthetic match
              </span>
            </div>
            <div className="timeline-track">
              <i
                style={{ width: `${Math.min(100, (clock / 5400000) * 100)}%` }}
              />
              {analyst.events
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
