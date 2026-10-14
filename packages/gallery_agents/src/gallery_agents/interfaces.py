from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from gallery_schema.models import MatchEvent


@dataclass(frozen=True)
class ViewerProfile:
    persona: str = "analyst"  # "analyst" | "casual" | ...
    favorite_team_id: str | None = None
    favorite_player_id: str | None = None
    language: str = "en"


@dataclass(frozen=True)
class OverlayCue:
    clock_ms: int
    template: str
    payload: dict
    duration_ms: int = 4000
    priority: int = 0


class Director(Protocol):
    async def on_event(self, event: MatchEvent) -> list[OverlayCue]: ...


class StatsAgent(Protocol):
    async def on_event(self, event: MatchEvent) -> dict: ...


class TacticsAgent(Protocol):
    async def on_event(self, event: MatchEvent) -> dict: ...


class StorylineAgent(Protocol):
    async def on_event(self, event: MatchEvent) -> dict: ...


class GraphicsAgent(Protocol):
    async def build_cues(self, insights: dict) -> list[OverlayCue]: ...


class ComplianceAgent(Protocol):
    async def validate(self, cue: OverlayCue) -> tuple[bool, list[str]]: ...


class WhatIfAgent(Protocol):
    async def run(self, match_id: str, clock_ms: int, query: str) -> dict: ...
