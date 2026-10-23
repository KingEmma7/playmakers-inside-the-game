from __future__ import annotations

from typing import Literal

import pytest
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient
from playmakers_agents.personalize import fan_phrase, significant_phrase
from playmakers_agents.players import player_name
from playmakers_agents.recap import team_name
from playmakers_agents.workflow import Director


@pytest.mark.asyncio
async def test_goals_are_named_scored_localized_and_verified_in_both_feeds() -> None:
    events = simulate_match(MatchConfig(seed=38))
    index = next(i for i, e in enumerate(events) if e.event_type == "goal")
    goal = events[index]
    profiles = [
        ViewerProfile(),
        *(
            ViewerProfile(persona="casual", language=lang, favorite_player_id=goal.scorer_player_id)
            for lang in ("en", "es", "fr")
        ),
    ]
    async with Director(
        client=DeterministicMockChatClient(), profiles=profiles, whatif_rollouts=2
    ) as director:
        for event in events[:index]:
            director.store.ingest_event(event.match_id, event)
        cues = [c for c in await director.on_event(goal) if c.template != "what_if"]
        assert len(cues) == 8
        for cue in cues:
            label = {"en": "GOAL", "es": "GOL", "fr": "BUT"}[cue.language]
            assert (
                cue.payload["headline"]
                == f"{label}, {player_name(goal.scorer_player_id)} {goal.clock_ms // 60000 + 1}'"
            )
            assert team_name(goal.scoring_team_id) in cue.payload["detail"]
            assert "1-0" in cue.payload["detail"]
            assert cue.payload["hold_ms"] == 60000
            assert goal.event_id in cue.evidence_event_ids
            assert cue.provenance.compliance == "verified"
            metric = "home_goals" if goal.scoring_team_id.endswith("_HOME") else "away_goals"
            assert cue.provenance.metrics[metric] == 1
            assert cue.provenance.metric_evidence[metric] == [goal.event_id]


@pytest.mark.parametrize("language", ["en", "es", "fr"])
def test_fan_phrases_are_event_driven_deterministic_and_do_not_repeat(
    language: Literal["en", "es", "fr"],
) -> None:
    events = simulate_match(MatchConfig(seed=38))
    previous = ""
    lines = []
    for event in events[:250]:
        if event.event_type == "goal":
            continue
        headline, detail = fan_phrase(event, language, previous)
        assert (headline, detail) == fan_phrase(event, language, previous)
        assert headline != previous
        assert "None" not in headline
        if event.event_type == "shot":
            assert player_name(event.shooter_player_id) in headline
        if event.event_type == "possession_change":
            assert "Northbridge Rovers" in headline or "Southport Athletic" in headline
        previous = headline
        lines.append(headline)
    assert len(set(lines)) > 25


@pytest.mark.asyncio
async def test_fan_rotation_through_workflow_passes_compliance() -> None:
    events = simulate_match(MatchConfig(seed=38))[:20]
    profiles = [
        ViewerProfile(persona="casual", language=lang, favorite_player_id="match_38_H09")
        for lang in ("en", "es", "fr")
    ]
    previous = {}
    async with Director(
        client=DeterministicMockChatClient(), profiles=profiles, whatif_rollouts=2
    ) as director:
        for event in events:
            cues = await director.on_event(event)
            for cue in cues[::2]:
                assert cue.payload["headline"] != previous.get(cue.language)
                assert cue.provenance.compliance == "verified"
                previous[cue.language] = cue.payload["headline"]


def test_red_cards_and_score_changes_use_event_fields() -> None:
    from playmakers_schema.models import CardEvent

    event = CardEvent(
        event_id="red",
        match_id="match_7",
        sequence=1,
        clock_ms=61000,
        period=1,
        carded_player_id="match_7_H09",
        color="red",
        reason="foul",
    )
    for lang, label in (("en", "RED CARD"), ("es", "TARJETA ROJA"), ("fr", "CARTON ROUGE")):
        assert significant_phrase(event, lang, 0, 0)[0] == f"{label}, Okafor 2'"
    goal = next(e for e in simulate_match(MatchConfig(seed=38)) if e.event_type == "goal")
    assert significant_phrase(goal, "en", 1, 1)[1] == "The score is level at 1-1."
    assert significant_phrase(goal, "en", 1, 2)[1] == "Southport Athletic lead 2-1."
