from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from gallery_schema.models import MatchEvent

from gallery_agents.contracts import Insight, OverlayCue


@dataclass
class MatchState:
    match_id: str
    events: deque[MatchEvent]
    insights: deque[Insight]
    overlay_cues: deque[OverlayCue]

    last_sequence: int = -1


class InMemoryMatchStore:
    """
    In-memory match blackboard for Phase 2.

    This is shaped so it can later be replaced by a Cosmos-backed implementation
    without changing callers.
    """

    def __init__(self, *, max_events: int = 200_000, max_insights: int = 50_000) -> None:
        self._matches: dict[str, MatchState] = {}
        self._max_events = max_events
        self._max_insights = max_insights
        self._by_event_id: dict[str, dict[str, MatchEvent]] = defaultdict(dict)

    def get_or_create(self, match_id: str) -> MatchState:
        if match_id not in self._matches:
            self._matches[match_id] = MatchState(
                match_id=match_id,
                events=deque(maxlen=self._max_events),
                insights=deque(maxlen=self._max_insights),
                overlay_cues=deque(maxlen=self._max_insights),
            )
        return self._matches[match_id]

    def ingest_event(self, match_id: str, event: MatchEvent) -> None:
        st = self.get_or_create(match_id)
        st.events.append(event)
        st.last_sequence = max(st.last_sequence, int(event.sequence))  # type: ignore[attr-defined]
        self._by_event_id[match_id][event.event_id] = event  # type: ignore[attr-defined]

    def get_event(self, match_id: str, event_id: str) -> MatchEvent:
        return self._by_event_id[match_id][event_id]

    def add_insight(self, match_id: str, insight: Insight) -> None:
        st = self.get_or_create(match_id)
        st.insights.append(insight)

    def add_overlay_cue(self, match_id: str, cue: OverlayCue) -> None:
        st = self.get_or_create(match_id)
        st.overlay_cues.append(cue)

    def list_events_since_sequence(self, match_id: str, sequence: int) -> list[MatchEvent]:
        st = self.get_or_create(match_id)
        return [e for e in st.events if int(e.sequence) > sequence]  # type: ignore[attr-defined]
