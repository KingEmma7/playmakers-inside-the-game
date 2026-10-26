from __future__ import annotations

from typing import Literal
from unittest.mock import AsyncMock

import pytest
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import OverlayCue, ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient
from playmakers_agents.personalize import (
    FAN_LINES,
    GOAL_THREAT_LINES,
    _fan_pattern,
    fan_phrase,
    goal_threat_phrase,
)
from playmakers_agents.state_store import InMemoryMatchStore
from playmakers_agents.workflow import AudienceExecutor, CuePacket
from playmakers_schema.models import CardEvent, MatchEvent, TrackingFrameEvent, Vec2

LANGUAGES = ("en", "es", "fr")


@pytest.mark.parametrize(
    ("language", "words"),
    [("es", ("pasa", "recibe", "balón")), ("fr", ("passe", "reçoit", "ballon"))],
)
def test_pass_variants_contain_language_words(language: str, words: tuple[str, ...]) -> None:
    for variant in FAN_LINES[language]["pass"]:
        assert any(word in variant for word in words), variant


@pytest.fixture(scope="module")
def examples() -> dict[str, MatchEvent]:
    events = simulate_match(MatchConfig(seed=38))
    samples = {event.event_type: event for event in events if event.event_type != "goal"}
    samples["pass"] = samples["pass"].model_copy(update={"completed": True, "pressure": 0.0})
    samples["incomplete"] = samples["pass"].model_copy(update={"completed": False})
    samples["pressure"] = samples["pass"].model_copy(update={"pressure": 0.9})
    samples["saved"] = samples["shot"].model_copy(update={"outcome": "saved"})
    samples["shot"] = samples["shot"].model_copy(update={"outcome": "off_target"})
    common = dict(event_id="sample", match_id="match_38", sequence=0, clock_ms=0, period=1)
    samples["card"] = CardEvent(
        **common, carded_player_id="match_38_H09", color="yellow", reason="foul"
    )
    samples["tracking_frame"] = TrackingFrameEvent(
        **common, ball_position=Vec2(x=52, y=34), players=[]
    )
    return samples


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("event_type", FAN_LINES["en"])
def test_fan_variety(
    language: Literal["en", "es", "fr"], event_type: str, examples: dict[str, MatchEvent]
) -> None:
    variants = FAN_LINES[language][event_type]
    assert len(variants) == len(set(variants)) == 8
    values = dict(player="Ellis", receiver="Mensah", team="Northbridge Rovers", color="yellow")
    for variant in variants:
        for other in variants:
            assert bool(_fan_pattern(variant).fullmatch(other.format(**values))) == (
                variant == other
            )

    def run() -> list[str]:
        lines: list[str] = []
        templates: list[str] = []
        for i in range(100):
            sample = examples[event_type]
            update = {
                field: f"match_38_H{(i + index) % 11 + 1:02}"
                for index, field in enumerate(sorted(sample.model_fields_set))
                if field.endswith("player_id") or field in ("player_in_id", "player_out_id")
            }
            event = sample.model_copy(update={**update, "event_id": f"variety:{i}"})
            prefix = {"en": "Favourite: ", "es": "Favorito: ", "fr": "Favori: "}[language]
            history = [prefix * (j % 3) + line for j, line in enumerate(lines)]
            headline, detail = fan_phrase(event, language, recent=history)
            matched = [variant for variant in variants if _fan_pattern(variant).fullmatch(headline)]
            assert len(matched) == 1
            assert matched[0] not in templates[-6:]
            templates.append(matched[0])
            assert headline not in lines[-6:]
            assert "None" not in headline + detail
            assert "{" not in headline + detail and "}" not in headline + detail
            lines.append(headline)
        assert len(set(lines)) >= 7
        return lines

    assert run() == run()


@pytest.mark.parametrize("language", LANGUAGES)
def test_fan_history_window_and_exhausted_fallback(
    language: Literal["en", "es", "fr"],
    examples: dict[str, MatchEvent],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = examples["pass"]
    baseline, _ = fan_phrase(event, language)
    variants = FAN_LINES[language]["pass"]
    chosen = next(variant for variant in variants if _fan_pattern(variant).fullmatch(baseline))
    previous = chosen.format(player="Bello", receiver="Novak")
    prefix = {"en": "Favourite: ", "es": "Favorito: ", "fr": "Favori: "}[language]
    assert fan_phrase(event, language, previous=prefix * 2 + previous)[0] != baseline
    assert fan_phrase(event, language, recent=[baseline] + ["unrelated"] * 6) == (baseline, "")
    # A reduced table can exhaust the window; selection must return to the hash offset.
    monkeypatch.setitem(FAN_LINES[language], "pass", variants[:2])
    baseline, _ = fan_phrase(event, language)
    history = [variant.format(player="Bello", receiver="Novak") for variant in variants[:2]]
    assert fan_phrase(event, language, recent=history) == (baseline, "")


@pytest.mark.parametrize("language", LANGUAGES)
def test_goal_threat_variety_has_no_time_promise(language: Literal["en", "es", "fr"]) -> None:
    assert len(set(GOAL_THREAT_LINES[language])) == 4
    previous = ""
    lines = set()
    for i in range(100):
        headline = goal_threat_phrase(str(i), "Northbridge Rovers", language, previous)
        assert headline == goal_threat_phrase(str(i), "Northbridge Rovers", language, previous)
        assert headline != previous
        assert "minut" not in headline.lower()
        assert "{" not in headline and "None" not in headline
        lines.add(headline)
        previous = headline
    assert len(lines) == 4


@pytest.mark.asyncio
async def test_audience_history_is_per_profile_and_shared_by_writers(
    examples: dict[str, MatchEvent],
) -> None:
    store = InMemoryMatchStore()
    event = examples["pass"]
    profiles = [
        ViewerProfile(persona="casual", language=lang, favorite_team_id=event.team_id)
        for lang in LANGUAGES
    ]
    audience = AudienceExecutor(profiles, store, DeterministicMockChatClient())
    ctx = AsyncMock()
    history: dict[int, list[str]] = {i: [] for i in range(len(profiles))}
    for i in range(40):
        current = event.model_copy(update={"event_id": f"audience:{i}", "sequence": i})
        store.ingest_event(current.match_id, current)
        cues = [
            OverlayCue(
                cue_id=f"{current.event_id}:{writer}",
                clock_ms=current.clock_ms,
                template="lower_third",
                payload={"headline": "", "detail": "", "metrics": {}},
                evidence_event_ids=[current.event_id],
            )
            for writer in ("tactics", "storyline")
        ]
        ctx.yield_output.reset_mock()
        await audience.handle(CuePacket(match_id=current.match_id, cues=cues), ctx)
        outputs = [
            call.args[0]
            for call in ctx.yield_output.call_args_list
            if isinstance(call.args[0], OverlayCue)
        ]
        for index in range(len(profiles)):
            first, second = outputs[index * 2 : index * 2 + 2]
            headline = first.payload["headline"]
            assert headline == second.payload["headline"]
            assert headline not in history[index][-6:]
            assert headline.startswith(
                {"en": "Favourite: ", "es": "Favorito: ", "fr": "Favori: "}[
                    profiles[index].language
                ]
            )
            history[index].append(headline)
