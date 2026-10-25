import { useEffect, useRef, useState } from "react";
import { apiBaseUrl } from "./stream";

type Answer = {
  answer: string;
  answerable: boolean;
  cited_event_ids: string[];
  source: "model" | "rules";
  note?: string | null;
};
export default function AskCrew({ seed, uptoEventId, language, onCitations }: {
  seed: number;
  uptoEventId?: string;
  language: string;
  onCitations: (ids: string[]) => void;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => pending.current?.abort(), []);
  function clear() {
    pending.current?.abort();
    setLoading(false);
    setAnswer(undefined);
    setError("");
    onCitations([]);
  }
  return <section className="ask-crew" aria-label="Ask the crew panel">
    <form onSubmit={async (e) => {
      e.preventDefault();
      if (!question.trim() || !uptoEventId) return;
      clear();
      const controller = new AbortController();
      pending.current = controller;
      setLoading(true);
      try {
        const response = await fetch(`${apiBaseUrl()}/ask`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ seed, upto_event_id: uptoEventId, question: question.trim(), language }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(response.status === 429 ? "Please wait before asking again." : "The crew could not answer. Try again.");
        const data: Answer = await response.json();
        if (controller.signal.aborted) return;
        setAnswer(data);
        onCitations(data.cited_event_ids);
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "The crew could not answer.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }}>
      <label htmlFor="ask-crew-question">Ask the crew</label>
      <div className="ask-controls">
        <input id="ask-crew-question" aria-label="Ask the crew" maxLength={200}
          placeholder="Why did Marin score?" value={question}
          onChange={(e) => { setQuestion(e.target.value); clear(); }} />
        <button type="submit" disabled={loading || !question.trim() || !uptoEventId}>Ask</button>
        {(answer || error) && <button type="button" onClick={() => { setQuestion(""); clear(); }}>Clear</button>}
      </div>
    </form>
    <div aria-live="polite">
      {loading && <p>Asking the crew…</p>}
      {error && <p role="alert">{error}</p>}
      {answer && <div className="ask-answer">
        <p>{answer.answer}</p>
        <small className="evidence" title={answer.cited_event_ids.join(", ")}>
          {answer.cited_event_ids.length > 0 && <>From events {answer.cited_event_ids.map((id) => String(Number(id.split(/[:_]/).at(-1)))).join(", ")}</>}
          {answer.source === "rules" && <span>{answer.cited_event_ids.length > 0 ? " · " : ""}Rule-based answer</span>}
        </small>
        {answer.note && <small>{answer.note}</small>}
      </div>}
    </div>
  </section>;
}
