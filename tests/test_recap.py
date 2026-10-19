from __future__ import annotations

import json

import pytest
from agent_framework import ChatResponse, Message
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient
from playmakers_agents.recap import key_moments, score
from playmakers_agents.workflow import Director, InsightPacket, recap_stats

PROFILES = [
    ViewerProfile(),
    ViewerProfile(persona="casual", language="es"),
    ViewerProfile(persona="casual", language="fr"),
]


async def recap_at_full_time(client: DeterministicMockChatClient) -> tuple[Director, list]:
    events = simulate_match(MatchConfig(seed=7))
    director = Director(client=client, profiles=PROFILES, whatif_rollouts=2)
    for event in events[:-1]:
        director.store.ingest_event(event.match_id, event)
    cues = await director.on_event(events[-1])
    return director, [cue for cue in cues if cue.template == "recap"]


@pytest.mark.asyncio
async def test_full_time_recap_is_offline_compliant_and_language_aware() -> None:
    director, cues = await recap_at_full_time(DeterministicMockChatClient())
    events = director.store.get_or_create("match_7").events
    home, away = score(events)
    ids = {e.event_id for e in events}
    assert [(c.persona, c.language) for c in cues] == [(p.persona, p.language) for p in PROFILES]
    assert [c.payload["headline"].split(":")[0] for c in cues] == [
        "Full time",
        "Final",
        "Fin du match ",
    ]
    for cue in cues:
        assert f"{home}–{away}" in cue.payload["headline"]
        assert cue.duration_ms == 30_000
        moments = cue.payload["moments"]
        assert 4 <= len(moments) <= 6
        assert [m["clock_ms"] for m in moments] == sorted(m["clock_ms"] for m in moments)
        assert {m["event_id"] for m in moments} <= set(cue.evidence_event_ids) <= ids
        assert cue.provenance.compliance == "verified"
        assert cue.provenance.metrics == {"home_goals": home, "away_goals": away}
    assert ("compliance", "recap_verified") in [(t.agent, t.action) for t in director.last_traces]


class TamperedScoreClient(DeterministicMockChatClient):
    async def _inner_get_response(self, **kwargs):
        response = await super()._inner_get_response(**kwargs)
        data = json.loads(response.text)
        if data.get("insight_id", "").endswith(":recap"):
            data["headline"] = "Full time: Northbridge Rovers 9–0 Southport Athletic"
            return ChatResponse(messages=[Message("assistant", [json.dumps(data)])])
        return response


@pytest.mark.asyncio
async def test_recap_with_a_tampered_score_is_rejected_and_replaced() -> None:
    director, cues = await recap_at_full_time(TamperedScoreClient())
    home, away = score(director.store.get_or_create("match_7").events)
    analyst = cues[0]
    assert analyst.provenance.compliance == "template_fallback"
    assert analyst.provenance.attempts == 3
    assert "Ungrounded number in prose" in analyst.provenance.reasons
    assert "9–0" not in analyst.payload["headline"]
    assert f"{home}–{away}" in analyst.payload["headline"]


@pytest.mark.asyncio
async def test_compliance_rejects_recap_moments_that_are_not_cited() -> None:
    director, cues = await recap_at_full_time(DeterministicMockChatClient())
    events = director.store.get_or_create("match_7").events
    stats = recap_stats(events, events[-1])
    packet = await director.writers[1].generate(stats, task={"task": "recap"})
    assert director.compliance.validate(packet).ok
    dropped = packet.insight.model_copy(
        update={"evidence_event_ids": packet.insight.evidence_event_ids[-1:]}
    )
    decision = director.compliance.validate(
        InsightPacket(stats=stats, insight=dropped, kind="storyline")
    )
    assert not decision.ok
    assert events[-1].event_type == "period_end"


def test_key_moments_prefer_goals_and_red_cards_then_fill_with_chances() -> None:
    events = simulate_match(MatchConfig(seed=7))
    goals = [e for e in events if e.event_type == "goal"]
    second_goal = events.index(goals[1])
    kinds = [m.kind for m in key_moments(events[: second_goal + 1])]
    assert len(kinds) == 4
    assert kinds.count("goal") == 2
    assert set(kinds) <= {"goal", "red_card", "big_chance", "chance"}
    assert [m.kind for m in key_moments(events)] == ["red_card"] + ["goal"] * 5
