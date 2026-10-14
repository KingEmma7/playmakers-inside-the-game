from __future__ import annotations

from dataclasses import dataclass, field

from gallery_schema.models import MatchEvent
from gallery_stats.engine import StatsEngine


@dataclass
class MatchStatsContext:
    engine: StatsEngine = field(default_factory=StatsEngine)


class StatsMcpService:
    def __init__(self) -> None:
        self._matches: dict[str, MatchStatsContext] = {}

    def _ctx(self, match_id: str) -> MatchStatsContext:
        if match_id not in self._matches:
            self._matches[match_id] = MatchStatsContext()
        return self._matches[match_id]

    def ingest_event(self, match_id: str, event: dict) -> dict:
        ev = MatchEvent.model_validate(event)
        self._ctx(match_id).engine.ingest(ev)
        return {"ok": True, "event_id": ev.event_id}

    def possession(self, match_id: str, match_clock_ms: int, window_ms: int = 120_000) -> dict:
        res = self._ctx(match_id).engine.possession(
            match_clock_ms=match_clock_ms, window_ms=window_ms
        )
        return res.model_dump(mode="json")

    def pressure_index(
        self, match_id: str, team_id: str, match_clock_ms: int, window_ms: int = 60_000
    ) -> dict:
        res = self._ctx(match_id).engine.pressure_index(
            team_id=team_id, match_clock_ms=match_clock_ms, window_ms=window_ms
        )
        return res.model_dump(mode="json")

    def pass_difficulty(self, match_id: str, event_id: str) -> dict:
        _ = match_id
        res = self._ctx(match_id).engine.pass_difficulty(event_id=event_id)
        return res.model_dump(mode="json")

    def xg(self, match_id: str, event_id: str) -> dict:
        _ = match_id
        res = self._ctx(match_id).engine.xg(event_id=event_id)
        return res.model_dump(mode="json")

    def momentum(self, match_id: str, match_clock_ms: int, window_ms: int = 180_000) -> dict:
        res = self._ctx(match_id).engine.momentum(
            match_clock_ms=match_clock_ms, window_ms=window_ms
        )
        return res.model_dump(mode="json")
