import { describe, expect, it } from "vitest";
import { countLabel, involvementLabel } from "./players";
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
    expect(involvementLabel(events, "H09", "es")).toBe("Okafor · 1 pase");
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
        "es",
      ),
    ).toBe("Okafor · 1 tiro");
  });
  it("falls back to touches or the name without inventing a count", () => {
    expect(involvementLabel(events.slice(1), "H09", "es")).toBe(
      "Okafor · 1 toque",
    );
    expect(involvementLabel([], "H09")).toBe("Okafor");
  });
  it("labels counts in the fan's language, singular and plural", () => {
    expect(involvementLabel(events, "H09")).toBe("Okafor · 1 pass");
    expect(involvementLabel(events, "H09", "fr")).toBe("Okafor · 1 passe");
    expect(involvementLabel([...events, events[0]], "H09", "es")).toBe(
      "Okafor · 2 pases",
    );
    expect(countLabel(1, "shot")).toBe("1 shot");
    expect(countLabel(0, "shot")).toBe("0 shots");
    expect(countLabel(2, "shot", "es")).toBe("2 tiros");
    expect(countLabel(2, "shot", "fr")).toBe("2 tirs");
    expect(countLabel(3, "touch", "fr")).toBe("3 touches");
    expect(countLabel(2, "pass", "de")).toBe("2 passes");
  });
});
