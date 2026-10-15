from __future__ import annotations

from dataclasses import dataclass

from playmakers_schema.models import MatchEvent


@dataclass(frozen=True)
class MatchMetrics:
    passes: int
    completed_passes: int
    shots: int
    goals: int
    fouls: int
    yellow_cards: int
    red_cards: int
    substitutions: int

    @property
    def pass_accuracy(self) -> float:
        return (self.completed_passes / self.passes) if self.passes else 0.0


def compute_metrics(events: list[MatchEvent]) -> MatchMetrics:
    passes = 0
    completed = 0
    shots = 0
    goals = 0
    fouls = 0
    yellows = 0
    reds = 0
    subs = 0

    for e in events:
        t = e.event_type  # type: ignore[attr-defined]
        if t == "pass":
            passes += 1
            if e.completed:  # type: ignore[attr-defined]
                completed += 1
        elif t == "shot":
            shots += 1
        elif t == "goal":
            goals += 1
        elif t == "foul":
            fouls += 1
        elif t == "card":
            if e.color == "yellow":  # type: ignore[attr-defined]
                yellows += 1
            else:
                reds += 1
        elif t == "substitution":
            subs += 1

    return MatchMetrics(
        passes=passes,
        completed_passes=completed,
        shots=shots,
        goals=goals,
        fouls=fouls,
        yellow_cards=yellows,
        red_cards=reds,
        substitutions=subs,
    )
