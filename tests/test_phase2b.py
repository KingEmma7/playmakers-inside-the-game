from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gallery_agents.contracts import OverlayCue, ViewerProfile
from gallery_agents.model_clients import DeterministicMockChatClient
from gallery_agents.resilience import KillSpec
from gallery_agents.what_if import WhatIfAgent
from gallery_agents.workflow import Director
from gallery_schema.models import CardEvent, GoalEvent
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from pitchsim.story import load_story
from pitchsim.whatif import rollout_from_snapshot, snapshot_from_events
from replay_api import main as api
from test_stats import passing, shot


@pytest.mark.asyncio
async def test_kill_fallback_restore_replay_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with Director(
        client=DeterministicMockChatClient(), checkpoint_path=str(tmp_path), kill="tactics@20"
    ) as director:
        await director.on_event(passing(clock=19 * 60000))
        original_agent = director.writers[0].agent
        cues = await director.on_event(passing(2, clock=20 * 60000))
        assert any(c.template == "template_fallback" for c in cues)
        assert {t.action for t in director.last_traces} >= {"agent_down", "fallback_on"}
        assert director.writers[0].agent_sequences["test"] == 1
        replayed = []
        generate = director.writers[0]._generate_raw

        async def record(stats, reasons=None):
            replayed.append(stats.event.sequence)
            return await generate(stats, reasons)

        monkeypatch.setattr(director.writers[0], "_generate_raw", record)
        cues = await director.on_event(passing(3, clock=20 * 60000 + 1000))
        assert replayed == [2, 3]  # Checkpoint event is not rerun; missed event is.
        assert director.writers[0].agent is not original_agent
        assert {t.action for t in director.last_traces} >= {
            "restarted_from_checkpoint",
            "caught_up",
        }
        assert all(c.template != "template_fallback" for c in cues)
        assert director.writers[0].agent_sequences["test"] == 3
    # Fresh process equivalent: restore shared evidence and continue without duplication.
    async with Director(
        client=DeterministicMockChatClient(), checkpoint_path=str(tmp_path)
    ) as restored:
        assert await restored.restore("test")
        assert [e.sequence for e in restored.store.get_or_create("test").events] == [1, 2, 3]
        cues = await restored.on_event(passing(4, clock=20 * 60000 + 2000))
        assert len(cues) == 2
        assert restored.writers[0].agent_sequences["test"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "exception"])
async def test_timeouts_and_circuit_backoff(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    async with Director(
        client=DeterministicMockChatClient(), timeouts={"tactics": 0.01, "graphics": 0.01}
    ) as director:
        calls = 0

        async def stalled(*args, **kwargs):
            nonlocal calls
            calls += 1
            if failure == "exception":
                raise RuntimeError("Injected crash")
            await asyncio.sleep(1)

        monkeypatch.setattr(director.writers[0], "_generate_raw", stalled)
        for sequence in range(1, 5):
            cues = await asyncio.wait_for(director.on_event(passing(sequence)), timeout=0.5)
            assert any(c.template == "template_fallback" for c in cues)
        assert calls == 3  # initial + two probes, with event 3 skipped by open breaker
        assert director.writers[0].breaker.failures == 3
        monkeypatch.setattr(director.graphics, "render", stalled)
        cues = await asyncio.wait_for(director.on_event(passing(5)), timeout=0.5)
        assert all(c.template == "template_fallback" for c in cues)
        assert any(
            t.agent == "graphics" and t.action == "fallback_on" for t in director.last_traces
        )


@pytest.mark.asyncio
async def test_profiles_differ_and_favorites_are_scoped() -> None:
    profiles = [
        ViewerProfile(),
        ViewerProfile(
            persona="casual", language="es", favorite_player_id="a", favorite_team_id="TEST_HOME"
        ),
        ViewerProfile(persona="casual", language="fr", favorite_player_id="other"),
    ]
    async with Director(client=DeterministicMockChatClient(), profiles=profiles) as director:
        cues = await director.on_event(passing())
        analyst, spanish, french = cues[0], cues[2], cues[4]
        assert analyst.payload["metrics"]["pressure_index"] == 0.4
        assert analyst.payload["tactical_label"]
        assert spanish.payload["metrics"] == {}
        assert "★" in spanish.payload["headline"]
        assert spanish.payload["player_cam"]["player_id"] == "a"
        assert "próximo" in spanish.payload["headline"]
        assert "attaque" in french.payload["headline"]
        assert all("player_cam" not in cue.payload for cue in (analyst, french))


@pytest.mark.asyncio
async def test_casual_whatif_preserves_rollout_count() -> None:
    from gallery_agents.personalize import personalize

    cue = OverlayCue(
        cue_id="whatif",
        clock_ms=0,
        template="what_if",
        evidence_event_ids=["e"],
        payload={
            "headline": "What if?",
            "detail": "Alternate outcome",
            "metrics": {
                "win_prob_before": 0.3,
                "win_prob_after": 0.6,
                "delta": 0.3,
                "rollouts": 20,
            },
        },
    )
    result = await personalize(
        cue,
        ViewerProfile(persona="casual", language="es"),
        passing(),
        DeterministicMockChatClient(),
        0,
    )
    assert result.payload["metrics"]["rollouts"] == 20


@pytest.mark.asyncio
async def test_whatif_determinism_triggers_and_probability_evidence() -> None:
    events = simulate_match(MatchConfig(seed=7))
    index = next(i for i, e in enumerate(events) if e.event_type == "goal")
    agent = WhatIfAgent(DeterministicMockChatClient(), rollouts=20, seed=7)
    try:
        cue = await agent.evaluate(events[: index + 1])
        again = await agent.evaluate(events[: index + 1])
        assert cue == again
        assert cue.evidence_event_ids[-1] == events[index].event_id
        metrics = cue.payload["metrics"]
        for name in ("before", "after", "counterfactual"):
            assert sum(metrics[name].values()) == pytest.approx(1)
        assert metrics["delta"] == metrics["win_prob_after"] - metrics["win_prob_before"]
        assert metrics["counterfactual"]["win"] == metrics["before"]["win"]
        assert "saved" in cue.payload["detail"]
        assert not agent.triggers(passing())
        big = shot().model_copy(update={"xg": 0.5, "outcome": "saved"})
        assert agent.triggers(big)
        assert not agent.triggers(big.model_copy(update={"xg": 0.3}))
        card = CardEvent(
            event_id="red",
            match_id="test",
            sequence=6,
            clock_ms=2000,
            period=1,
            team_id="TEST_HOME",
            carded_player_id="a",
            color="red",
            reason="synthetic",
        )
        assert agent.triggers(card)
        red = await agent.evaluate([passing(), card])
        assert "red card" in red.payload["scenario"]
        chance = await agent.evaluate([passing(), big])
        assert "scored" in chance.payload["scenario"]
    finally:
        await agent.close()


def test_snapshot_scores_nullable_team_and_rollout() -> None:
    goal = GoalEvent(
        event_id="g",
        match_id="test",
        sequence=6,
        clock_ms=5400000,
        period=2,
        scoring_team_id="TEST_HOME",
        scorer_player_id="a",
        shot_event_id="e5",
    )
    config = MatchConfig()
    snapshot = snapshot_from_events(
        [passing(), shot(), goal], home_style=config.home_style, away_style=config.away_style
    )
    assert snapshot.home_score == 1
    assert rollout_from_snapshot(snapshot, rollout_seed=5) == (1, 0)


def test_story_scripts_are_seeded_and_plant_labels() -> None:
    for path, label in (
        ("stories/press_collapse.yaml", "press_collapse_after_60"),
        ("stories/late_comeback.yaml", "late_comeback_attempt"),
    ):
        config = MatchConfig(seed=7, story=load_story(path))
        events = simulate_match(config)
        assert events == simulate_match(config)
        assert any(label in event.labels for event in events)
    with pytest.raises(ValueError):
        KillSpec.parse("stats@20")


def test_gallery_sse_ws_and_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "simulate_match", lambda config: [passing(), passing(2)])
    with TestClient(api.app) as client:
        response = client.get(
            "/gallery/sse?speed=0&kill=tactics@0&persona=casual&language=es&whatif_rollouts=20",
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        messages = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        assert {m["type"] for m in messages} == {"event", "cue", "trace"}
        assert {m.get("action") for m in messages} >= {
            "agent_down",
            "fallback_on",
            "restarted_from_checkpoint",
            "caught_up",
        }
        assert all(m["language"] == "es" for m in messages if m["type"] == "cue")
        with client.websocket_connect("/gallery/ws?speed=0&whatif_rollouts=20") as ws:
            rows = [ws.receive_json() for _ in range(9)]
            assert {m["type"] for m in rows} == {"event", "cue", "trace"}
        assert client.get("/gallery/sse?kill=invalid").status_code == 422
        assert client.get("/gallery/sse?whatif_rollouts=0").status_code == 422
        assert client.get("/gallery/sse?language=xx").status_code == 422


@pytest.mark.asyncio
async def test_live_translation_and_number_preserving_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib import import_module
    from types import SimpleNamespace

    from gallery_agents.contracts import OverlayCue

    module = import_module("gallery_agents.personalize")
    text = '{"headline": "Analyse traduite", "detail": "Mesures vérifiées."}'

    class Translator:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, prompt):
            return SimpleNamespace(text=text)

    monkeypatch.setattr(module, "Agent", Translator)
    cue = OverlayCue(
        cue_id="translation",
        clock_ms=1000,
        template="tactics",
        payload={
            "headline": "Passing under pressure",
            "detail": "Verified metrics.",
            "metrics": {},
        },
        evidence_event_ids=["e1"],
    )
    profile = ViewerProfile(language="fr")
    translated = await module.personalize(cue, profile, passing(), object(), 0)
    assert translated.payload["headline"] == "Analyse traduite"
    text = '{"headline": "Invented 99", "detail": "Mesures vérifiées."}'
    fallback = await module.personalize(cue, profile, passing(), object(), 0)
    assert fallback.payload["headline"] == "Analyse du match"
    assert "99" not in str(fallback.payload)
