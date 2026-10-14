import { useState } from "react";
import { ViewPanel, Crest } from "./Overlay";
import TracePanel from "./TracePanel";
import { useGalleryStream, clockLabel } from "./stream";
function About() {
  return (
    <main className="about">
      <a href="/">← Back to live gallery</a>
      <span className="eyebrow">BUILT FOR THE PRODUCTION GALLERY</span>
      <h1>
        One match.
        <br />
        An entire AI crew.
      </h1>
      <p>
        Gallery turns a seeded, synthetic football match into evidence-backed
        broadcast overlays and a personalised second screen. Every club, player
        and match is fictional.
      </p>
      <div className="architecture">
        PitchSim → Replay API → Director
        <br />↙ Stats MCP · Tactics · Storyline · What-If ↘<br />
        Compliance → Graphics → Audience → Your screen
      </div>
      <h2>Seven roles. One verified story.</h2>
      <p>
        Microsoft Agent Framework coordinates specialist agents. Deterministic
        Stats tools provide numbers through MCP. Compliance checks claims
        against event IDs. Graphics validates timed cues, and Audience shapes
        the same moment for analysts and fans in English, Spanish or French.
      </p>
      <h2>Built to keep broadcasting.</h2>
      <p>
        Kill Tactics during a match: deterministic captions take over within one
        event. The agent reloads its checkpoint and catches up. What-If uses
        parallel, seeded PitchSim continuations to explain alternative outcomes.
      </p>
      <h2>What is running here?</h2>
      <p>
        The local demo uses an offline mock model, in-memory state and file
        checkpoints. Foundry/Azure OpenAI model clients are available when
        configured. Cosmos DB, Container Apps deployment and cloud observability
        are planned for Phase 4; this page does not claim they are deployed.
      </p>
      <p className="muted">
        Player motion is a formation-based visualisation around observed
        ball/action positions; it is not real tracking data. What-If
        probabilities are illustrative synthetic continuations.
      </p>
    </main>
  );
}
export default function App() {
  return location.pathname === "/about" ? <About /> : <Gallery />;
}
function Gallery() {
  const [seed, setSeed] = useState(7);
  const [speed, setSpeed] = useState(10);
  const [language, setLanguage] = useState<"es" | "fr">("es");
  const [favourite, setFavourite] = useState("H09");
  const [safe, setSafe] = useState(false);
  const [running, setRunning] = useState(true);
  const [pausedSequence, setPausedSequence] = useState(-1);
  const [replayFrom, setReplayFrom] = useState(0);
  const [kill, setKill] = useState<string>();
  const [notice, setNotice] = useState(
    "Two audiences. One shared match clock.",
  );
  const analyst = useGalleryStream({
    seed,
    speed,
    persona: "analyst",
    language: "en",
    kill,
    replay_from_ms: replayFrom,
  });
  const fan = useGalleryStream({
    seed,
    speed,
    persona: "casual",
    language,
    favourite_player_id: favourite ? `match_${seed}_${favourite}` : undefined,
    kill,
    replay_from_ms: replayFrom,
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
    setNotice("Replay restarted for both audiences.");
  }
  return (
    <div className="app-shell">
      <header>
        <a className="brand" href="/">
          <span className="brand-mark">g</span>gallery
          <span className="brand-divider" />
          <small>
            PRODUCTION
            <br />
            INTELLIGENCE
          </small>
        </a>
        <nav>
          <span className="live-badge">● LIVE SIMULATION</span>
          <a href="/about">Inside Gallery ↗</a>
        </nav>
      </header>
      <div className="workspace-title">
        <div>
          <span className="eyebrow">MATCHDAY / SYNTHETIC REPLAY</span>
          <h1>The game, through every lens.</h1>
        </div>
        <div className="match-title">
          <Crest />
          <span>
            Northbridge Rovers<small>vs Southport Athletic</small>
          </span>
          <Crest away />
        </div>
      </div>
      <section className="toolbar" aria-label="Replay controls">
        <div className="control">
          <label htmlFor="seed">MATCH SEED</label>
          <input
            id="seed"
            type="number"
            min="0"
            max="999999"
            value={seed}
            onChange={(e) => {
              setSeed(Math.max(0, Math.min(999999, Number(e.target.value))));
              restart();
            }}
          />
        </div>
        <div className="control">
          <label htmlFor="speed">REPLAY SPEED</label>
          <select
            id="speed"
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
          {running ? "Ⅱ Pause" : "▶ Start"}
        </button>
        <span className="toolbar-divider" />
        <div className="control">
          <label htmlFor="language">FAN LANGUAGE</label>
          <select
            id="language"
            value={language}
            onChange={(e) => {
              setLanguage(e.target.value as "es" | "fr");
              setNotice("Fan feed replaying to synchronise the new profile.");
            }}
          >
            <option value="es">Español</option>
            <option value="fr">Français</option>
          </select>
        </div>
        <div className="control favourite-control">
          <label htmlFor="favourite">FAVOURITE PLAYER</label>
          <select
            id="favourite"
            value={favourite}
            onChange={(e) => setFavourite(e.target.value)}
          >
            <option value="">No favourite</option>
            {["H", "A"].flatMap((team) =>
              Array.from({ length: 11 }, (_, i) => {
                const id = `${team}${String(i + 1).padStart(2, "0")}`;
                return (
                  <option key={id} value={id}>
                    {team === "H" ? "Northbridge" : "Southport"} #{i + 1}
                  </option>
                );
              }),
            )}
          </select>
        </div>
        <label className="safe-toggle">
          <input
            type="checkbox"
            checked={safe}
            onChange={(e) => setSafe(e.target.checked)}
          />
          Safe areas
        </label>
        <time className="shared-clock">{clockLabel(clock)}</time>
      </section>
      <main className="gallery-layout">
        <div className="program-area">
          <div className="split-view">
            <ViewPanel
              title="ANALYST"
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
              title="FAN"
              persona="casual"
              event={fan.events.find((e) => e.sequence === sequence)}
              events={fan.events}
              cues={fan.cues}
              clock={clock}
              safe={safe}
              running={running}
              status={fan.status}
            />
          </div>
          <div className="session-note" role="status">
            <span className="pulse" />
            {running
              ? notice
              : "Program paused. Incoming events are buffered; Start returns to the live clock."}
            <span>
              {sequence >= 0
                ? `EVENT ${String(sequence).padStart(4, "0")} · SYNCED`
                : "SYNCING FEEDS"}
            </span>
          </div>
          <section className="production-notes">
            <div>
              <span className="eyebrow">01 / GROUNDED</span>
              <h2>Every number has a source.</h2>
              <p>
                Deterministic stats. Event-level evidence. A compliance check
                before a graphic reaches the screen.
              </p>
            </div>
            <div>
              <span className="eyebrow">02 / RESILIENT</span>
              <h2>The broadcast stays on air.</h2>
              <p>
                Checkpoint recovery and safe templates keep the story moving
                when an agent goes down.
              </p>
            </div>
            <div>
              <span className="eyebrow">03 / PERSONAL</span>
              <h2>Same moment. Your perspective.</h2>
              <p>
                Analytical depth on one screen. A favourite player and familiar
                language on the other.
              </p>
            </div>
          </section>
          <footer>
            FICTIONAL CLUBS · SYNTHETIC DATA · OFFLINE MODEL DEMO
            <span>Formation-based player motion · observed ball positions</span>
          </footer>
        </div>
        <TracePanel
          traces={traces}
          disabled={!event || !running || Boolean(kill)}
          onKill={() => {
            const minute = Math.floor(clock / 60000);
            setReplayFrom(Math.floor(clock / 60000) * 60000);
            setKill(`tactics@${minute}`);
            setNotice(
              `Both feeds restarted · Tactics failure scheduled at ${minute}′. Recovery traces will appear at that moment.`,
            );
          }}
        />
      </main>
    </div>
  );
}
