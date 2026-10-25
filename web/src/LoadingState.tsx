import { useEffect, useRef, useState } from "react";

const SHOW_DELAY_MS = 250;
const MIN_VISIBLE_MS = 400;
const FADE_MS = 180;

export default function LoadingState({
  waiting,
  reconnecting = false,
}: {
  waiting: boolean;
  reconnecting?: boolean;
}) {
  const [phase, setPhase] = useState<"hidden" | "visible" | "fading">("hidden");
  const shownAt = useRef<number | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let fadeTimer: ReturnType<typeof setTimeout>;
    if (waiting) {
      timer = setTimeout(() => {
        shownAt.current ??= Date.now();
        setPhase("visible");
      }, shownAt.current === null ? SHOW_DELAY_MS : 0);
    } else if (shownAt.current !== null) {
      const remaining = Math.max(0, MIN_VISIBLE_MS - (Date.now() - shownAt.current));
      timer = setTimeout(() => {
        setPhase("fading");
        fadeTimer = setTimeout(() => {
          shownAt.current = null;
          setPhase("hidden");
        }, FADE_MS);
      }, remaining);
    }
    return () => {
      clearTimeout(timer);
      clearTimeout(fadeTimer);
    };
  }, [waiting]);

  if (phase === "hidden") return null;

  return (
    <div className={`loading-scrim${phase === "fading" ? " is-fading" : ""}`}>
      <div className="loading-card" role="status" aria-live="polite">
        <svg className="loading-spinner" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
        </svg>
        <span>{reconnecting ? "Reconnecting to the match…" : "Getting the match ready…"}</span>
      </div>
    </div>
  );
}
