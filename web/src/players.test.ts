import { describe, expect, it } from "vitest";
import { involvementLabel } from "./players";
import type { MatchEvent } from "./stream";

describe("favourite involvement", () => {
  const events = [
    {
      event_type: "pass",
      from_player_id: "match_7_H09",
      to_player_id: "match_7_H01",
    },
    {
      event_type: "pass",
      from_player_id: "match_7_H01",
      to_player_id: "match_7_H09",
    },
    { event_type: "shot", shooter_player_id: "match_7_A09" },
  ] as MatchEvent[];
  it("uses observed passes, then shots when the favourite shoots", () => {
    expect(involvementLabel(events, "H09")).toBe("Okafor · 1 pases");
    expect(
      involvementLabel(
        [
          ...events,
          {
            event_type: "shot",
            shooter_player_id: "match_7_H09",
          } as MatchEvent,
        ],
        "H09",
      ),
    ).toBe("Okafor · 1 tiros");
  });
  it("falls back to touches or the name without inventing a count", () => {
    expect(involvementLabel(events.slice(1), "H09")).toBe("Okafor · 1 toques");
    expect(involvementLabel([], "H09")).toBe("Okafor");
  });
});
