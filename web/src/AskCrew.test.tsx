import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useState } from "react";
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
  function Panels() {
    const [ids, setIds] = useState<string[]>();
    return <>{["casual", "analyst"].map((persona) => <ViewPanel key={persona}
      seed={7} title={persona} persona={persona} events={events} event={shot}
      cues={[]} clock={shot.clock_ms} safe={false} running={false} status="live"
      citedIds={ids} onCitations={setIds} />)}</>;
  }
  render(<Panels />);
  fireEvent.change(screen.getByLabelText("Ask the crew"), { target: { value: "shots?" } });
  fireEvent.click(screen.getByRole("button", { name: /^Ask$/ }));
  expect(await screen.findByText("A shot was recorded.")).toBeInTheDocument();
  expect(screen.getByText(`From events ${Number(shot.event_id.split(":").at(-1))}`)).toHaveClass("evidence");
  expect(screen.getByText(/Rule-based answer/)).toBeInTheDocument();
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ seed: 7, upto_event_id: shot.event_id });
  await waitFor(() => screen.getAllByTestId("pitch-trail").forEach((pitch) => expect(pitch).toHaveTextContent("1")));
  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(screen.queryByText("A shot was recorded.")).not.toBeInTheDocument();
  screen.getAllByTestId("pitch-trail").forEach((pitch) => expect(pitch).toHaveTextContent("0"));
});
