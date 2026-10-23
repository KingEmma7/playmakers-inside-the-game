import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { usePlaymakersStream } from "./stream";

vi.mock("./stream", async (original) => ({
  ...await original<typeof import("./stream")>(),
  usePlaymakersStream: vi.fn(() => ({ events: [], cues: [], traces: [], status: "connecting" })),
}));
vi.mock("./Pitch", () => ({ default: () => <div /> }));
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  history.replaceState(null, "", "/");
});
it("introduces the crew, hides on About and remembers dismissal for the session", () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: async () => ({ live: false }) }));
  const { unmount } = render(<App />);
  expect(screen.getByRole("note")).toHaveTextContent("8 AI and rule-based agents");
  expect(screen.getByLabelText("MATCH SEED")).toHaveValue(382);
  fireEvent.click(screen.getByRole("link", { name: "About" }));
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "Replay" }));
  fireEvent.click(screen.getByRole("button", { name: "Dismiss introduction" }));
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
  unmount();
  render(<App />);
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
});

it("holds the shared clock, score and captions while failure replay catches up", () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: async () => ({ live: false }) }));
  const event = (sequence: number, clock_ms: number): import("./stream").MatchEvent => ({
    schema_version: "1.0.0", event_type: "period_start", event_id: `e${sequence}`,
    match_id: "match_382", sequence, clock_ms, period: 1, labels: [],
  });
  const caption: import("./stream").OverlayCue = {
    cue_id: "held", clock_ms: 210000, template: "tactics", evidence_event_ids: ["e10"],
    payload: { headline: "Held caption", detail: "From the current match." },
  };
  const original = { generation: "normal", events: [event(10, 211000)], cues: [caption], traces: [], status: "live" };
  let replay = { ...original, generation: "recovery", events: [] as import("./stream").MatchEvent[], cues: [] as import("./stream").OverlayCue[] };
  vi.mocked(usePlaymakersStream).mockImplementation((params) => params.kill ? replay : original);
  const { container, rerender } = render(<App />);
  expect(container.querySelector(".shared-clock")).toHaveTextContent("03:31");
  fireEvent.click(screen.getByRole("button", { name: "Stop Tactics agent" }));
  expect(container.querySelector(".shared-clock")).toHaveTextContent("03:31");
  expect(screen.getAllByText("Held caption")).toHaveLength(2);
  replay = { ...replay, events: [event(1, 38000)] };
  rerender(<App />);
  expect(container.querySelector(".shared-clock")).toHaveTextContent("03:31");
  replay = { ...replay, events: [event(10, 211000), event(11, 212000)], cues: [caption] };
  rerender(<App />);
  expect(container.querySelector(".shared-clock")).toHaveTextContent("03:32");
});
