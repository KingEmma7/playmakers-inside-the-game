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
