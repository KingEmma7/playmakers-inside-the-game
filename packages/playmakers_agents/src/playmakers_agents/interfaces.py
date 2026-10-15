from __future__ import annotations

from typing import Protocol

from playmakers_schema.models import MatchEvent
from playmakers_stats.types import PlaymakersStatsBaseModel

from playmakers_agents.contracts import ComplianceDecision, Insight, OverlayCue
from playmakers_agents.contracts import ViewerProfile as ViewerProfile


class Director(Protocol):
    async def on_event(self, event: MatchEvent) -> list[OverlayCue]: ...


class StatsAgent(Protocol):
    async def on_event(self, event: MatchEvent) -> dict[str, PlaymakersStatsBaseModel]: ...


class TacticsAgent(Protocol):
    async def on_event(self, event: MatchEvent) -> Insight: ...


class StorylineAgent(Protocol):
    async def on_event(self, event: MatchEvent) -> Insight: ...


class GraphicsAgent(Protocol):
    async def build_cues(self, insights: list[Insight]) -> list[OverlayCue]: ...


class ComplianceAgent(Protocol):
    async def validate(self, cue: OverlayCue) -> ComplianceDecision: ...


class WhatIfAgent(Protocol):
    async def run(self, match_id: str, clock_ms: int, query: str) -> Insight: ...
