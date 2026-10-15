from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp.server.fastmcp import FastMCP
from playmakers_schema.models import MatchEvent
from playmakers_stats.engine import StatsEngine
from playmakers_stats.types import (
    ControlChaosResult,
    MomentumResult,
    PassDifficultyResult,
    PossessionResult,
    PressureIndexResult,
    XGResult,
)
from pydantic import BaseModel, TypeAdapter


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

    def ingest_event(self, match_id: str, event: dict[str, Any]) -> IngestResult:
        ev = TypeAdapter(MatchEvent).validate_python(event)
        if ev.match_id != match_id:
            raise ValueError("match_id does not match event")
        self._ctx(match_id).engine.ingest(ev)
        return IngestResult(ok=True, event_id=ev.event_id)

    def possession(
        self, match_id: str, match_clock_ms: int, window_ms: int = 120_000
    ) -> PossessionResult:
        res = self._ctx(match_id).engine.possession(
            match_clock_ms=match_clock_ms, window_ms=window_ms
        )
        return res

    def pressure_index(
        self, match_id: str, team_id: str, match_clock_ms: int, window_ms: int = 60_000
    ) -> PressureIndexResult:
        res = self._ctx(match_id).engine.pressure_index(
            team_id=team_id, match_clock_ms=match_clock_ms, window_ms=window_ms
        )
        return res

    def pass_difficulty(self, match_id: str, event_id: str) -> PassDifficultyResult:
        res = self._ctx(match_id).engine.pass_difficulty(event_id=event_id)
        return res

    def xg(self, match_id: str, event_id: str) -> XGResult:
        res = self._ctx(match_id).engine.xg(event_id=event_id)
        return res

    def momentum(
        self, match_id: str, match_clock_ms: int, window_ms: int = 180_000
    ) -> MomentumResult:
        res = self._ctx(match_id).engine.momentum(
            match_clock_ms=match_clock_ms, window_ms=window_ms
        )
        return res

    def control_vs_chaos(
        self, match_id: str, team_id: str, match_clock_ms: int, window_ms: int = 120_000
    ) -> ControlChaosResult:
        return self._ctx(match_id).engine.control_vs_chaos(
            team_id=team_id, match_clock_ms=match_clock_ms, window_ms=window_ms
        )


class IngestResult(BaseModel):
    ok: bool
    event_id: str


def create_mcp(*, host: str = "127.0.0.1", port: int = 8765, path: str = "/mcp") -> FastMCP:
    service = StatsMcpService()
    server = FastMCP(
        "playmakers-stats",
        host=host,
        port=port,
        streamable_http_path=path,
        stateless_http=True,
        json_response=True,
    )
    for name in (
        "ingest_event",
        "possession",
        "pressure_index",
        "pass_difficulty",
        "xg",
        "momentum",
        "control_vs_chaos",
    ):
        server.tool(name=name)(getattr(service, name))
    return server
