from __future__ import annotations

from typing import Protocol

from playmakers_schema.models import MatchEvent
from pydantic import BaseModel, Field

from playmakers_agents.contracts import Insight, OverlayCue


class MatchState(BaseModel):
    match_id: str
    events: list[MatchEvent] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    overlay_cues: list[OverlayCue] = Field(default_factory=list)
    last_sequence: int = -1


class MatchStore(Protocol):
    def get_or_create(self, match_id: str) -> MatchState: ...
    def ingest_event(self, match_id: str, event: MatchEvent) -> None: ...
    def get_event(self, match_id: str, event_id: str) -> MatchEvent: ...
    def add_insight(self, match_id: str, insight: Insight) -> None: ...
    def add_overlay_cue(self, match_id: str, cue: OverlayCue) -> None: ...
    def list_events_since_sequence(self, match_id: str, sequence: int) -> list[MatchEvent]: ...


class InMemoryMatchStore:
    def __init__(self) -> None:
        self._matches: dict[str, MatchState] = {}
        self._events: dict[tuple[str, str], MatchEvent] = {}

    def get_or_create(self, match_id: str) -> MatchState:
        if match_id not in self._matches:
            self._matches[match_id] = MatchState(match_id=match_id)
        return self._matches[match_id]

    def ingest_event(self, match_id: str, event: MatchEvent) -> None:
        if match_id != event.match_id:
            raise ValueError("match_id does not match event")
        state = self.get_or_create(match_id)
        if event.sequence <= state.last_sequence:
            raise ValueError("Events must have strictly increasing sequence")
        state.events.append(event)
        state.last_sequence = event.sequence
        self._events[match_id, event.event_id] = event

    def get_event(self, match_id: str, event_id: str) -> MatchEvent:
        return self._events[match_id, event_id]

    def add_insight(self, match_id: str, insight: Insight) -> None:
        self.get_or_create(match_id).insights.append(insight)

    def add_overlay_cue(self, match_id: str, cue: OverlayCue) -> None:
        self.get_or_create(match_id).overlay_cues.append(cue)

    def list_events_since_sequence(self, match_id: str, sequence: int) -> list[MatchEvent]:
        return [e for e in self.get_or_create(match_id).events if e.sequence > sequence]
