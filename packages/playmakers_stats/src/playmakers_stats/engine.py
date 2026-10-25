from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from math import log2
from typing import Any

from playmakers_schema.models import MatchEvent

from playmakers_stats.threat import GoalThreat, ThreatTracker
from playmakers_stats.types import (
    ControlChaosResult,
    Evidence,
    MomentumResult,
    PassDifficultyResult,
    PossessionResult,
    PressureIndexResult,
    XGResult,
)


@dataclass
class _EventRow:
    clock_ms: int
    event_id: str
    event_type: str
    team_id: str | None
    payload: dict[str, Any]


class StatsEngine:
    """
    Deterministic stats computed over a rolling window of match events.

    The engine is fed with `MatchEvent`s in order (by `sequence`).
    """

    def __init__(self, *, max_events: int = 50_000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._events: deque[_EventRow] = deque(maxlen=max_events)
        self._match_id: str | None = None
        self._last_sequence = -1
        self.threat_tracker = ThreatTracker()

    def ingest(self, event: MatchEvent) -> None:
        if self._match_id not in (None, event.match_id):
            raise ValueError("StatsEngine handles one match")
        if event.sequence <= self._last_sequence:
            raise ValueError("Events must have strictly increasing sequence")
        self.threat_tracker.ingest(event)
        self._match_id = event.match_id
        self._last_sequence = event.sequence
        self._events.append(
            _EventRow(
                clock_ms=event.clock_ms,
                event_id=event.event_id,
                event_type=event.event_type,
                team_id=event.team_id,
                payload=event.model_dump(mode="json"),
            )
        )

    def _window(self, *, match_clock_ms: int, window_ms: int) -> list[_EventRow]:
        if match_clock_ms < 0 or window_ms < 0:
            raise ValueError("Clock and window must be nonnegative")
        start = max(0, match_clock_ms - window_ms)
        return [e for e in self._events if start <= e.clock_ms <= match_clock_ms]

    def possession(self, *, match_clock_ms: int, window_ms: int = 120_000) -> PossessionResult:
        """
        Approximate possession as share of completed on-ball actions (passes + carries) by team.
        """
        window = self._window(match_clock_ms=match_clock_ms, window_ms=window_ms)
        home = 0
        away = 0
        evidence: list[str] = []

        for e in window:
            if e.event_type == "pass":
                completed = bool(e.payload.get("completed"))
                if not completed:
                    continue
                evidence.append(e.event_id)
                team_id = e.payload.get("team_id")
                if team_id and team_id.endswith("_HOME"):
                    home += 1
                elif team_id and team_id.endswith("_AWAY"):
                    away += 1
            elif e.event_type == "carry":
                evidence.append(e.event_id)
                team_id = e.payload.get("team_id")
                if team_id and team_id.endswith("_HOME"):
                    home += 1
                elif team_id and team_id.endswith("_AWAY"):
                    away += 1

        total = home + away
        if total == 0:
            return PossessionResult(
                home_possession=0.5, away_possession=0.5, evidence=Evidence(event_ids=[])
            )

        return PossessionResult(
            home_possession=home / total,
            away_possession=away / total,
            evidence=Evidence(event_ids=evidence),
        )

    def pressure_index(
        self, *, team_id: str, match_clock_ms: int, window_ms: int = 60_000
    ) -> PressureIndexResult:
        """
        0..1 proxy based on average opponent pressure recorded on on-ball events.
        """
        window = self._window(match_clock_ms=match_clock_ms, window_ms=window_ms)
        pressures: list[float] = []
        evidence: list[str] = []

        for e in window:
            if e.payload.get("team_id") != team_id:
                continue
            if e.event_type in ("pass", "carry"):
                p = e.payload.get("pressure")
                if isinstance(p, (int, float)):
                    pressures.append(float(p))
                    evidence.append(e.event_id)
            if e.event_type == "shot":
                p = (e.payload.get("ground_truth") or {}).get("pressure")
                if isinstance(p, (int, float)):
                    pressures.append(float(p))
                    evidence.append(e.event_id)

        if not pressures:
            return PressureIndexResult(
                team_id=team_id, pressure_index=0.0, evidence=Evidence(event_ids=[])
            )

        avg = sum(pressures) / len(pressures)
        return PressureIndexResult(
            team_id=team_id,
            pressure_index=max(0.0, min(1.0, avg)),
            evidence=Evidence(event_ids=evidence),
        )

    def pass_difficulty(self, *, event_id: str) -> PassDifficultyResult:
        for e in reversed(self._events):
            if e.event_id == event_id:
                if e.event_type != "pass":
                    raise ValueError(f"event_id {event_id} is not a pass")
                return PassDifficultyResult(
                    event_id=event_id,
                    difficulty=float(e.payload["difficulty"]),
                    pressure=float(e.payload["pressure"]),
                    completed=bool(e.payload["completed"]),
                    evidence=Evidence(event_ids=[event_id]),
                )
        raise KeyError(f"Unknown event_id: {event_id}")

    def xg(self, *, event_id: str) -> XGResult:
        for e in reversed(self._events):
            if e.event_id == event_id:
                if e.event_type != "shot":
                    raise ValueError(f"event_id {event_id} is not a shot")
                return XGResult(
                    event_id=event_id,
                    xg=float(e.payload["xg"]),
                    outcome=e.payload["outcome"],
                    evidence=Evidence(event_ids=[event_id]),
                )
        raise KeyError(f"Unknown event_id: {event_id}")

    def momentum(self, *, match_clock_ms: int, window_ms: int = 180_000) -> MomentumResult:
        """
        Simple momentum proxy: rolling (shots + 2*goals) difference.
        """
        window = self._window(match_clock_ms=match_clock_ms, window_ms=window_ms)
        home = 0.0
        away = 0.0
        evidence: list[str] = []

        for e in window:
            if e.event_type == "shot":
                evidence.append(e.event_id)
                if (e.team_id or "").endswith("_HOME"):
                    home += 1.0
                elif (e.team_id or "").endswith("_AWAY"):
                    away += 1.0
            elif e.event_type == "goal":
                evidence.append(e.event_id)
                scoring_team = str(e.payload["scoring_team_id"])
                if scoring_team.endswith("_HOME"):
                    home += 2.0
                elif scoring_team.endswith("_AWAY"):
                    away += 2.0

        denom = max(1.0, home + away)
        score = (home - away) / denom
        return MomentumResult(
            home_momentum=max(-1.0, min(1.0, score)),
            away_momentum=max(-1.0, min(1.0, -score)),
            evidence=Evidence(event_ids=evidence),
        )

    def control_vs_chaos(
        self, *, team_id: str, match_clock_ms: int, window_ms: int = 120_000
    ) -> ControlChaosResult:
        """Normalized entropy of completed directed pass edges and failed-pass share.

        Entropy is zero for a single edge; one for equally used multiple edges.
        Turnovers count failed passes once, avoiding duplicate possession-change records.
        """
        passes = [
            e
            for e in self._window(match_clock_ms=match_clock_ms, window_ms=window_ms)
            if e.team_id == team_id and e.event_type == "pass"
        ]
        edges = Counter(
            (e.payload["from_player_id"], e.payload["to_player_id"])
            for e in passes
            if e.payload["completed"]
        )
        total = sum(edges.values())
        entropy = (
            (-sum((n / total) * log2(n / total) for n in edges.values()) / log2(len(edges)))
            if len(edges) > 1
            else 0.0
        )
        return ControlChaosResult(
            team_id=team_id,
            pass_network_entropy=max(0.0, min(1.0, entropy)),
            turnover_rate=sum(not e.payload["completed"] for e in passes) / len(passes)
            if passes
            else 0.0,
            evidence=Evidence(event_ids=[e.event_id for e in passes]),
        )

    def goal_threat(self, *, team_id: str, match_clock_ms: int) -> GoalThreat:
        return self.threat_tracker.predict(team_id, match_clock_ms)
