"""Live models answer with prose and metric names; numbers, ids and evidence come from code."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agent_framework import ChatResponse, Message
from playmakers_agents import personalize as personalize_module
from playmakers_agents.contracts import CueProvenance, OverlayCue, ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient
from playmakers_agents.workflow import Director, describe_moment, quotable
from test_stats import passing


def every_event(event) -> bool:
    return True


class ShortReplyClient(DeterministicMockChatClient):
    """Answers the way the live prompt asks: three keys, no ids, clock or evidence."""

    def __init__(self, reply: dict) -> None:
        super().__init__()
        self.reply = reply
        self.prompts: list[dict] = []

    async def _inner_get_response(self, *, messages, **kwargs):
        self.prompts.append(
            json.loads(next(m.text for m in reversed(messages) if m.role == "user"))
        )
        return ChatResponse(messages=[Message("assistant", [json.dumps(self.reply)])])


@pytest.mark.asyncio
async def test_metric_names_become_verified_values_and_missing_ids_come_from_the_handoff() -> None:
    client = ShortReplyClient(
        {
            "headline": "Calm build-up",
            "detail": "A pass rated 0.6 for difficulty.",
            "metrics": ["difficulty"],
        }
    )
    cues = await Director(client=client, model_events=every_event).on_event(passing())
    analyst = [c for c in cues if c.template in ("tactics", "storyline")]
    assert len(analyst) == 2
    for cue in analyst:
        assert cue.provenance.source == "agent"
        assert cue.provenance.compliance == "verified"
        assert cue.provenance.attempts == 1
        assert cue.provenance.metrics == {"difficulty": 0.6}
        assert cue.evidence_event_ids == ["e1"]
    prompt = client.prompts[0]
    assert prompt["quotable"]["difficulty"] == "0.6"
    assert "position" not in json.dumps(prompt["moment"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        {"headline": "Shot speed", "detail": "Hit at 98 km/h.", "metrics": ["shot_speed_kmh"]},
        {
            "headline": "Calm",
            "detail": "A pass rated 0.6.",
            "metrics": ["difficulty"],
            "clock_ms": 7,
        },
        {"headline": "Calm", "detail": "Rated 0.6.", "metrics": ["difficulty"], "kind": "pass"},
    ],
)
async def test_unknown_metric_names_and_wrong_supplied_fields_are_still_rejected(
    reply: dict,
) -> None:
    cues = await Director(client=ShortReplyClient(reply), model_events=every_event).on_event(
        passing()
    )
    for cue in cues:
        assert cue.provenance.compliance == "template_fallback"
        assert cue.provenance.attempts == 3


def test_moment_uses_names_and_carries_no_numbers_or_ids() -> None:
    event = passing().model_copy(
        update={"from_player_id": "match_7_H09", "to_player_id": "match_7_A01"}
    )
    moment = describe_moment(event)
    assert moment["from_player"] == "Okafor"
    assert moment["to_player"] == "Bello"
    assert moment["event_type"] == "pass"
    assert not any(ch.isdigit() for ch in json.dumps(moment))
    assert quotable({"home_possession": 0.5437, "turnover_rate": 0.125, "xg": 0.3}) == {
        "home_possession": "54.37%",
        "turnover_rate": "12.5%",
        "xg": "0.3",
    }


@pytest.mark.asyncio
async def test_only_model_written_analyst_captions_are_sent_for_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Translator:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, prompt):
            calls.append(prompt)
            return SimpleNamespace(text='{"headline": "Analyse", "detail": "Mesures."}')

    monkeypatch.setattr(personalize_module, "Agent", Translator)

    def cue(source: str) -> OverlayCue:
        return OverlayCue(
            cue_id=source,
            clock_ms=1000,
            template="tactics",
            payload={"headline": "Calm build-up", "detail": "Verified.", "metrics": {}},
            evidence_event_ids=["e1"],
            provenance=CueProvenance(agent="tactics", source=source, compliance="verified"),
        )

    live = object()
    for persona in ("analyst", "casual"):
        profile = ViewerProfile(persona=persona, language="fr")
        await personalize_module.personalize(cue("template"), profile, passing(), live, 0)
    assert calls == []
    fan = ViewerProfile(persona="casual", language="fr")
    await personalize_module.personalize(cue("agent"), fan, passing(), live, 0)
    assert calls == []
    analyst = ViewerProfile(language="fr")
    translated = await personalize_module.personalize(cue("agent"), analyst, passing(), live, 0)
    assert len(calls) == 1
    assert translated.payload["headline"] == "Analyse"
