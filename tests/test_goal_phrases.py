from __future__ import annotations

import pytest
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient
from playmakers_agents.personalize import PHRASES, goal_phrase
from playmakers_agents.players import player_name
from playmakers_agents.recap import team_name
from playmakers_agents.workflow import Director, InsightPacket, compute_stats

FANS = [ViewerProfile(persona="casual", language=lang) for lang in ("en", "es", "fr")]


@pytest.mark.asyncio
async def test_casual_goal_line_names_scorer_and_team_and_passes_compliance() -> None:
    events = simulate_match(MatchConfig(seed=7))
    index = next(i for i, e in enumerate(events) if e.event_type == "goal")
    goal = events[index]
    async with Director(
        client=DeterministicMockChatClient(), profiles=FANS, whatif_rollouts=2
    ) as director:
        for event in events[:index]:
            director.store.ingest_event(event.match_id, event)
        cues = [c for c in await director.on_event(goal) if c.template != "what_if"]
        stats = compute_stats(director.engines[goal.match_id], goal)
        verified = director.store.get_or_create(goal.match_id).insights[-1]
        scorer, team = player_name(goal.scorer_player_id), team_name(goal.scoring_team_id)
        assert scorer and team
        assert {c.language for c in cues} == {"en", "es", "fr"}
        for cue in cues:
            assert scorer in cue.payload["headline"] and team in cue.payload["headline"]
            assert cue.payload["headline"] != PHRASES[cue.language][0]
            casual = verified.model_copy(
                update={
                    "headline": cue.payload["headline"],
                    "detail": cue.payload["detail"],
                    "metrics": stats.metrics,
                    "evidence_event_ids": stats.evidence_event_ids,
                }
            )
            decision = director.compliance.validate(
                InsightPacket(stats=stats, insight=casual, kind=verified.kind)
            )
            assert decision.ok, decision.reasons


def test_goal_phrases_vary_deterministically_by_seed_and_event() -> None:
    goals = [
        e
        for seed in (7, 42, 1)
        for e in simulate_match(MatchConfig(seed=seed))
        if e.event_type == "goal"
    ]
    lines = [goal_phrase(g, "es") for g in goals]
    assert lines == [goal_phrase(g, "es") for g in goals]
    assert len({detail for _, detail in lines}) >= 2
    assert all(not any(ch.isdigit() for ch in h + d) for h, d in lines)
