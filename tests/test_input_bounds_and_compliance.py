from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_agents.model_clients import DeterministicMockChatClient
from playmakers_agents.what_if import WhatIfAgent
from playmakers_agents.workflow import Director, InsightPacket, compute_stats
from replay_api import main as api
from test_stats import passing


def test_seed_and_speed_are_bounded() -> None:
    with TestClient(api.app) as client:
        assert client.get("/playmakers/sse?seed=-1&whatif_rollouts=1").status_code == 422
        assert client.get("/playmakers/sse?speed=-1&whatif_rollouts=1").status_code == 422
        assert client.get("/playmakers/sse?speed=101&whatif_rollouts=1").status_code == 422
        assert client.get("/playmakers/sse?seed=10001&whatif_rollouts=1").status_code == 422


def test_whatif_pool_getattr_without_lifespan_state() -> None:
    pool = api._whatif_pool(api.app)
    assert pool is None or isinstance(pool, ProcessPoolExecutor)


@pytest.mark.asyncio
async def test_whatif_evidence_capped_and_ends_with_trigger() -> None:
    events = simulate_match(MatchConfig(seed=7))
    index = next(i for i, e in enumerate(events) if e.event_type == "goal")
    agent = WhatIfAgent(DeterministicMockChatClient(), rollouts=20, seed=7)
    try:
        cue = await agent.evaluate(events[: index + 1])
        assert cue is not None
        assert cue.evidence_event_ids[-1] == events[index].event_id
        assert len(cue.evidence_event_ids) <= 8
    finally:
        await agent.close()


@pytest.mark.asyncio
async def test_compliance_validates_against_stats_packet() -> None:
    async with Director(client=DeterministicMockChatClient()) as director:
        event = passing()
        await director.on_event(event)
        stats = compute_stats(director.engines[event.match_id], event)
        bad = InsightPacket(
            stats=stats,
            kind="tactics",
            insight=None,
            error="agent_unavailable",
        )
        assert not director.compliance.validate(bad).ok


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prose", "allowed"),
    [
        ("Shirt 9 moves at 20:35", True),
        ("Number 99 presses", True),
        ("Pressure is 73%", False),
        ("Jersey 100 advances", False),
        ("Pressure is 9", False),
    ],
)
async def test_structural_numbers_do_not_hide_unverified_metrics(prose: str, allowed: bool) -> None:
    from playmakers_agents.contracts import Insight

    async with Director() as director:
        event = passing()
        await director.on_event(event)
        stats = compute_stats(director.engines[event.match_id], event)
        packet = InsightPacket(
            stats=stats,
            kind="tactics",
            insight=Insight(
                insight_id="structural",
                kind="tactics",
                clock_ms=event.clock_ms,
                headline=prose,
                detail="Movement",
                evidence_event_ids=[event.event_id],
            ),
        )
        assert director.compliance.validate(packet).ok is allowed


@pytest.mark.parametrize(
    ("prose", "allowed"),
    [
        ("A 3-3 draw", True),
        ("A 3–3 draw", True),
        ("Three apiece", True),
        ("A 3-4 defeat", False),
        ("Momentum -3 at the end", False),
        ("Level at 3-3 after 90 minutes", False),
    ],
)
def test_scores_read_as_two_numbers_and_each_must_be_verified(prose: str, allowed: bool) -> None:
    from pitchsim.config import MatchConfig
    from pitchsim.sim import simulate_match
    from playmakers_agents.contracts import Insight
    from playmakers_agents.workflow import recap_stats

    events = simulate_match(MatchConfig(seed=89))  # a 3-3 draw
    stats = recap_stats(events, events[-1])
    assert stats.metrics == {"home_goals": 3, "away_goals": 3}
    insight = Insight(
        insight_id="recap",
        kind="storyline",
        clock_ms=events[-1].clock_ms,
        headline=prose,
        detail="Full time.",
        metrics=dict(stats.metrics),
        evidence_event_ids=list(stats.evidence_event_ids),
    )
    packet = InsightPacket(stats=stats, kind="storyline", insight=insight)
    assert Director().compliance.validate(packet).ok is allowed
