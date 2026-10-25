import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ViewPanel } from "./Overlay";
import fixture from "./fixtures/seed7-events.json";
import type { MatchEvent } from "./stream";

vi.mock("./Pitch", () => ({ default: ({ trail }: { trail: unknown[] }) => <div data-testid="pitch-trail">{trail.length}</div> }));
afterEach(() => vi.unstubAllGlobals());

it("asks at the displayed cutoff, renders the answer and replaces pitch citations", async () => {
  const events = fixture as unknown as MatchEvent[];
  const shot = events.find((e) => e.event_type === "shot")!;
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    answer: "A shot was recorded.", answerable: true, source: "rules", cited_event_ids: [shot.event_id],
  }) });
  vi.stubGlobal("fetch", fetch);
  render(<ViewPanel seed={7} title="For you" persona="casual" events={events} event={shot}
    cues={[]} clock={shot.clock_ms} safe={false} running={false} status="live" />);
  fireEvent.change(screen.getByLabelText("Ask the crew"), { target: { value: "shots?" } });
  fireEvent.click(screen.getByRole("button", { name: /^Ask$/ }));
  expect(await screen.findByText("A shot was recorded.")).toBeInTheDocument();
  expect(screen.getByText(/Based on 1 events/)).toHaveTextContent("Rule-based answer");
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ seed: 7, upto_event_id: shot.event_id });
  await waitFor(() => expect(screen.getByTestId("pitch-trail")).toHaveTextContent("1"));
  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(screen.queryByText("A shot was recorded.")).not.toBeInTheDocument();
  expect(screen.getByTestId("pitch-trail")).toHaveTextContent("0");
});
