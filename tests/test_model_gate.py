from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from conftest import serve
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient
from playmakers_agents.workflow import (
    Director,
    InsightPacket,
    compute_stats,
    key_moment,
    templated_insight,
)
from playmakers_stats.engine import StatsEngine
from stats_mcp.server import create_mcp
from test_stats import passing, shot


class CountingClient(DeterministicMockChatClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: Counter[str] = Counter()
        self.tool_calls: list[tuple[str, bool]] = []

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        data = json.loads(next(m.text for m in reversed(messages) if m.role == "user"))
        self.calls[data.get("task") or data["kind"]] += 1
        if "event" in data:
            self.tool_calls.append((data["event"]["event_type"], bool(options.get("tools"))))
        return super()._inner_get_response(
            messages=messages, stream=stream, options=options, **kwargs
        )


@pytest.mark.asyncio
async def test_mock_match_spends_model_calls_on_key_moments_only() -> None:
    events = simulate_match(MatchConfig(seed=7))
    client = CountingClient()
    profiles = [ViewerProfile(), ViewerProfile(persona="casual")]
    async with Director(client=client, profiles=profiles, seed=7, whatif_rollouts=2) as director:
        for event in events:
            await director.on_event(event)
    key = sum(key_moment(e) for e in events)
    assert client.calls["tactics"] == client.calls["storyline"] == key == 102
    assert client.calls["what_if_explanation"] == 9
    assert client.calls["recap"] == 1
    assert sum(client.calls.values()) == 214 <= 260  # Was 3,148 when every event called both.


@pytest.mark.asyncio
async def test_routine_events_get_templated_insights_that_pass_compliance() -> None:
    events = simulate_match(MatchConfig(seed=42))[:400]
    director = Director(client=DeterministicMockChatClient())
    engine = StatsEngine()
    routine = 0
    headlines: set[str] = set()
    for event in events:
        engine.ingest(event)
        if key_moment(event):
            continue
        routine += 1
        stats = compute_stats(engine, event)
        for kind in ("tactics", "storyline"):
            insight = templated_insight(stats, kind)
            packet = InsightPacket(stats=stats, insight=insight, kind=kind, templated=True)
            assert director.compliance.validate(packet).ok, (insight.headline, insight.detail)
            assert any(ch.isdigit() for ch in insight.detail)
            assert "index" not in f"{insight.headline} {insight.detail}".lower()
            headlines.add(insight.headline)
    assert routine > 300
    assert "Routine pass under light pressure" in headlines
    assert "Northbridge Rovers on the ball" in headlines
    cues = await director.on_event(passing())
    assert [c.template for c in cues] == ["tactics", "storyline"]
    assert cues[0].payload["headline"] == "Testing pass under moderate pressure"
    assert cues[0].payload["detail"] == (
        "Northbridge Rovers keep the ball moving; this pass rated 0.6 for difficulty."
    )
    assert cues[1].payload["detail"] == "Momentum is even, at 0."
    for cue in cues:
        assert cue.provenance.source == "template"
        assert cue.provenance.compliance == "verified"
        assert cue.provenance.attempts == 1
    assert [t.action for t in director.last_traces if t.agent == "tactics"] == ["templated"]


@pytest.mark.asyncio
async def test_stats_tools_are_offered_to_models_only_on_shots_and_goals() -> None:
    events = simulate_match(MatchConfig(seed=7))[:60]
    client = CountingClient()
    async with serve(create_mcp().streamable_http_app()) as base_url:
        async with Director(
            client=client, stats_mcp_url=base_url + "/mcp", whatif_rollouts=2
        ) as director:
            for event in events:
                await director.on_event(event)
    assert {"shot", "kickoff", "pass"} <= {kind for kind, _ in client.tool_calls}
    assert all(tools == (kind in ("shot", "goal")) for kind, tools in client.tool_calls)


@pytest.mark.asyncio
async def test_recovery_replays_only_gated_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with Director(
        client=DeterministicMockChatClient(), checkpoint_path=str(tmp_path), kill="tactics@20"
    ) as director:
        await director.on_event(passing(clock=19 * 60000))
        cues = await director.on_event(passing(2, clock=20 * 60000))
        assert any(c.template == "template_fallback" for c in cues)
        replayed = []
        generate = director.writers[0]._generate_raw

        async def record(stats, reasons=None):
            replayed.append(stats.event.sequence)
            return await generate(stats, reasons)

        monkeypatch.setattr(director.writers[0], "_generate_raw", record)
        late_shot = shot(3).model_copy(update={"clock_ms": 20 * 60000 + 1000})
        cues = await director.on_event(late_shot)
        assert replayed == [3]  # The missed routine pass is not sent to the model again.
        assert all(c.template != "template_fallback" for c in cues)
        assert director.writers[0].agent_sequences["test"] == 3
