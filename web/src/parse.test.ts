import { describe, expect, it } from "vitest";
import { parseStreamMessage } from "./parse";

const event = {
  type: "event",
  schema_version: "1.0.0",
  event_id: "e1",
  match_id: "m",
  sequence: 3,
  clock_ms: 1200,
  period: 1,
  event_type: "kickoff",
  team_id: "home",
};

describe("parseStreamMessage", () => {
  it("accepts each wire message kind", () => {
    expect(parseStreamMessage(JSON.stringify(event))).toMatchObject({
      kind: "event",
      event: { sequence: 3, event_type: "kickoff" },
    });
    expect(
      parseStreamMessage(
        JSON.stringify({
          type: "cue",
          cue_id: "c1",
          clock_ms: 0,
          template: "tactics",
          payload: {},
          evidence_event_ids: ["e1"],
        }),
      ),
    ).toMatchObject({ kind: "cue", cue: { cue_id: "c1" } });
    expect(
      parseStreamMessage(
        JSON.stringify({ type: "trace", agent: "stats", action: "computed", latency_ms: 1, status: "ok" }),
      ),
    ).toMatchObject({ kind: "trace", trace: { agent: "stats" } });
  });

  it("rejects malformed frames instead of passing them through", () => {
    expect(parseStreamMessage("not json")).toEqual({ kind: "invalid" });
    expect(parseStreamMessage(JSON.stringify({ ...event, sequence: "3" }))).toEqual({ kind: "invalid" });
    expect(parseStreamMessage(JSON.stringify({ type: "cue", cue_id: "c1" }))).toEqual({ kind: "invalid" });
    expect(parseStreamMessage(JSON.stringify({ type: "trace", agent: 1 }))).toEqual({ kind: "invalid" });
    expect(parseStreamMessage(JSON.stringify({ type: "heartbeat" }))).toEqual({ kind: "ignored" });
  });
});
