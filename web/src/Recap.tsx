import { useState } from "react";
import {
  minute,
  momentLabel,
  RECAP_COPY,
  recapMoments,
  recapText,
} from "./recapText";
import type { OverlayCue } from "./stream";

export function RecapCard({
  cue,
  focus,
  onFocus,
  onExplain,
}: {
  cue: OverlayCue;
  focus?: string;
  onFocus: (eventId?: string) => void;
  onExplain: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const language = cue.language ?? "en";
  const copy = RECAP_COPY[language];
  const text = recapText(cue);
  const copyText = async () => {
    await navigator.clipboard?.writeText(text);
    setCopied(true);
  };
  const share = async () => {
    if ("share" in navigator) {
      await navigator
        .share({ title: String(cue.payload.headline), text })
        .catch(() => {});
    } else {
      await copyText();
    }
  };
  return (
    <section className="recap" aria-label={copy.label}>
      <h3>{String(cue.payload.headline ?? "")}</h3>
      <p>{String(cue.payload.detail ?? "")}</p>
      <ol className="recap-moments">
        {recapMoments(cue.payload).map((m) => (
          <li key={m.event_id}>
            <button
              type="button"
              aria-pressed={focus === m.event_id}
              onClick={() =>
                onFocus(focus === m.event_id ? undefined : m.event_id)
              }
            >
              <time>{minute(m.clock_ms)}</time>{" "}
              {momentLabel(m, language, cue.persona !== "casual")}
            </button>
          </li>
        ))}
      </ol>
      <div className="recap-actions">
        <button type="button" onClick={copyText}>
          {copy.copy}
        </button>
        <button type="button" onClick={share}>
          {copy.share}
        </button>
        <button type="button" className="why" onClick={onExplain}>
          {copy.why}
        </button>
        <span role="status">{copied ? copy.copied : ""}</span>
      </div>
    </section>
  );
}
