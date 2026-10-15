from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pitchsim.config import MatchConfig, StoryEvent
from pitchsim.sim import _apply_story, simulate_match
from pitchsim.story import load_story
from pitchsim.whatif import rollout_from_snapshot, snapshot_from_events
from playmakers_agents.contracts import AgentTraceEvent, OverlayCue
from playmakers_schema.models import MatchEvent


def test_snapshot_reconstructs_scripted_styles_and_rollouts() -> None:
    config = MatchConfig(seed=7, story=load_story("stories/press_collapse.yaml"))
    events = simulate_match(config)
    applied = next(e for e in events if (e.ground_truth or {}).get("style_changes"))
    prefix = [e for e in events if e.sequence <= applied.sequence]
    snapshot = snapshot_from_events(
        prefix, home_style=config.home_style, away_style=config.away_style
    )
    expected_home, expected_away = config.home_style, config.away_style
    for e in prefix:
        for raw in (e.ground_truth or {}).get("style_changes", []):
            change = StoryEvent.model_validate(raw)
            if change.team == "home":
                expected_home, _ = _apply_story(expected_home, change)
            else:
                expected_away, _ = _apply_story(expected_away, change)
        if e.event_type == "card" and e.color == "red":
            change = StoryEvent(minute=0, type="red_card", team="home")
            if (e.team_id or "").endswith("_HOME"):
                expected_home, _ = _apply_story(expected_home, change)
            else:
                expected_away, _ = _apply_story(expected_away, change)
    assert snapshot.home_style == expected_home
    assert snapshot.away_style == expected_away
    assert snapshot.home_style != config.home_style or snapshot.away_style != config.away_style
    # Supplying the source schedule must not double-apply recorded changes.
    with_schedule = snapshot_from_events(
        prefix, home_style=config.home_style, away_style=config.away_style, story=config.story
    )
    assert with_schedule == snapshot
    expected = snapshot.model_copy(
        update={"home_style": expected_home, "away_style": expected_away}
    )
    outcomes = [rollout_from_snapshot(snapshot, rollout_seed=i) for i in range(12)]
    assert outcomes == [rollout_from_snapshot(expected, rollout_seed=i) for i in range(12)]
    assert outcomes == [rollout_from_snapshot(snapshot, rollout_seed=i) for i in range(12)]


def test_future_style_change_applied_once_in_rollout() -> None:
    config = MatchConfig(seed=4)
    event = simulate_match(config)[0]
    change = StoryEvent(minute=0, type="press_collapse", team="away")
    snapshot = snapshot_from_events(
        [event], home_style=config.home_style, away_style=config.away_style
    )
    updated, _ = _apply_story(config.away_style, change)
    pending = snapshot.model_copy(update={"story": [change]})
    applied = snapshot.model_copy(update={"away_style": updated})
    assert [rollout_from_snapshot(pending, rollout_seed=i) for i in range(10)] == [
        rollout_from_snapshot(applied, rollout_seed=i) for i in range(10)
    ]


@pytest.mark.asyncio
async def test_playmakers_failure_replay_fast_forwards_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from playmakers_agents.contracts import ViewerProfile
    from replay_api import main as api

    events = simulate_match(MatchConfig(seed=3))[:5]
    calls = []

    class DirectorStub:
        last_traces: list[AgentTraceEvent] = []

        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> DirectorStub:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def on_event(self, event: MatchEvent) -> list[OverlayCue]:
            return []

    async def replay(items: list[MatchEvent], *, speed: float) -> AsyncGenerator[MatchEvent, None]:
        calls.append((items, speed))
        for item in items:
            yield item

    monkeypatch.setattr(api, "Director", DirectorStub)
    monkeypatch.setattr(api, "simulate_match", lambda config: events)
    monkeypatch.setattr(api, "replay_events", replay)
    cutoff = events[3].clock_ms
    messages = [
        message
        async for message in api.playmakers_messages(
            3, 10, ViewerProfile(), "tactics@0", 2, replay_from_ms=cutoff
        )
    ]
    assert [m["event_id"] for m in messages] == [e.event_id for e in events]
    assert calls == [
        ([e for e in events if e.clock_ms < cutoff], 0),
        ([e for e in events if e.clock_ms >= cutoff], 10),
    ]
