from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_framework import ChatResponse, Message
from conftest import serve
from jsonschema import validate
from playmakers_agents.contracts import OverlayCue, ViewerProfile
from playmakers_agents.model_clients import (
    DeterministicMockChatClient,
    create_playmakers_chat_client,
)
from playmakers_agents.workflow import Director, InsightPacket, compute_stats
from stats_mcp.server import create_mcp
from test_stats import passing, shot


@pytest.mark.asyncio
async def test_workflow_fan_out_and_grounded_cues(tmp_path: Path) -> None:
    director = Director(
        client=DeterministicMockChatClient(),
        profiles=[ViewerProfile(), ViewerProfile(persona="casual")],
        checkpoint_path=str(tmp_path),
    )
    cues = await director.on_event(passing())
    assert len(cues) == 4
    assert {cue.persona for cue in cues} == {"analyst", "casual"}
    assert all(cue.evidence_event_ids == ["e1"] for cue in cues)
    assert all(
        cue.payload["metrics"]["difficulty"] == 0.6 for cue in cues if cue.persona == "analyst"
    )
    assert all(cue.payload["metrics"] == {} for cue in cues if cue.persona == "casual")
    assert {trace.agent for trace in director.last_traces} == {
        "stats",
        "tactics",
        "storyline",
        "compliance",
        "graphics",
        "audience",
    }
    assert all(trace.status == "ok" for trace in director.last_traces)
    assert director.store.get_event("test", "e1").event_id == "e1"
    assert len(director.store.list_events_since_sequence("test", 0)) == 1
    files = list(tmp_path.glob("*.json"))
    assert len(files) >= 5  # Every superstep must save successfully, not just run completion.
    assert len(director.store.get_or_create("test").insights) == 2
    # Stored framework checkpoints must actually deserialize with the configured allowlist.
    storage = director.checkpoint_storage
    for file in files:
        assert await storage.load(file.stem)
    next_cues = await director.on_event(shot())
    assert next_cues[0].payload["metrics"]["xg"] == 0.3


class InventingClient(DeterministicMockChatClient):
    def __init__(self, failures: int = 100) -> None:
        super().__init__()
        self.failures = failures
        self.calls = 0

    async def _inner_get_response(self, **kwargs):
        self.calls += 1
        response = await super()._inner_get_response(**kwargs)
        if self.calls <= self.failures:
            data = json.loads(response.text)
            data["metrics"]["difficulty"] = 0.999
            data["detail"] = "An invented 99 percent chance."
            return ChatResponse(messages=[Message("assistant", [json.dumps(data)])])
        return response


@pytest.mark.asyncio
async def test_two_retries_then_template() -> None:
    client = InventingClient()
    director = Director(client=client)
    cues = await director.on_event(passing())
    assert client.calls == 6  # Two branches, initial attempt plus two retries each.
    assert all(cue.template == "template_fallback" for cue in cues)
    assert all(cue.payload["metrics"] == {} for cue in cues)
    assert all(cue.evidence_event_ids == ["e1"] for cue in cues)
    assert sum(t.status == "retry" for t in director.last_traces) == 4
    assert any(t.status == "fallback" for t in director.last_traces)


@pytest.mark.asyncio
async def test_correction_can_pass_before_retry_limit() -> None:
    client = InventingClient(failures=2)
    director = Director(client=client)
    cues = await director.on_event(passing())
    assert client.calls == 4
    assert all(cue.template != "template_fallback" for cue in cues)


@pytest.mark.asyncio
async def test_cues_explain_their_agent_stats_and_compliance_verdict() -> None:
    director = Director(
        client=DeterministicMockChatClient(),
        profiles=[ViewerProfile(), ViewerProfile(persona="casual")],
    )
    cues = await director.on_event(passing())
    assert {cue.provenance.agent for cue in cues} == {"tactics", "storyline"}
    for cue in cues:
        assert cue.provenance.compliance == "verified"
        assert cue.provenance.source == "agent"
        assert cue.provenance.attempts == 1
        assert cue.provenance.personalized_for == cue.persona
        assert cue.provenance.metrics["difficulty"] == 0.6
        cited = set(cue.evidence_event_ids)
        assert all(set(ids) <= cited for ids in cue.provenance.metric_evidence.values())
    casual = next(cue for cue in cues if cue.persona == "casual")
    assert casual.payload["metrics"] == {}
    assert casual.provenance.insight_headline != casual.payload["headline"]


@pytest.mark.asyncio
async def test_provenance_records_rejections_retries_and_template_fallback() -> None:
    corrected = await Director(client=InventingClient(failures=2)).on_event(passing())
    assert all(cue.provenance.compliance == "verified" for cue in corrected)
    assert all(cue.provenance.attempts == 2 for cue in corrected)
    assert all("Ungrounded metric: difficulty" in cue.provenance.reasons for cue in corrected)
    failed = await Director(client=InventingClient()).on_event(passing())
    for cue in failed:
        assert cue.provenance.compliance == "template_fallback"
        assert cue.provenance.source == "template"
        assert cue.provenance.attempts == 3
        assert cue.provenance.metrics == {}
        assert cue.provenance.reasons


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    ["no_evidence", "future_evidence", "number", "metric", "missing_metric_evidence", "clock"],
)
async def test_compliance_rejects_ungrounded_handoffs(change: str) -> None:
    director = Director(client=DeterministicMockChatClient())
    await director.on_event(passing())
    await director.on_event(passing(2, target="c"))
    stats = compute_stats(director.engines["test"], passing(2, target="c"))
    packet = await director.writers[0].generate(stats)
    insight = packet.insight
    assert insight is not None
    if change == "no_evidence":
        insight.evidence_event_ids = []
    elif change == "future_evidence":
        insight.evidence_event_ids.append("unknown")
    elif change == "number":
        insight.detail = "A chance of 98%."
    elif change == "metric":
        insight.metrics["invented"] = 42
    elif change == "missing_metric_evidence":
        insight.evidence_event_ids = ["e2"]
    else:
        insight.clock_ms = 0
    assert not director.compliance.validate(
        InsightPacket(stats=stats, insight=insight, kind="tactics")
    ).ok


@pytest.mark.asyncio
async def test_agent_framework_mcp_transport() -> None:
    async with serve(create_mcp().streamable_http_app()) as base_url:
        async with Director(
            client=DeterministicMockChatClient(), stats_mcp_url=base_url + "/mcp"
        ) as director:
            cues = await director.on_event(passing())
            assert cues[0].payload["metrics"]["difficulty"] == 0.6
            assert cues[0].template == "tactics"


def test_default_client_ignores_unrelated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_AI_PROJECT_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "irrelevant")
    assert isinstance(create_playmakers_chat_client(), DeterministicMockChatClient)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid")
    assert isinstance(create_playmakers_chat_client(), DeterministicMockChatClient)
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://example.invalid")
    with pytest.raises(ValueError, match="AZURE_AI_MODEL_DEPLOYMENT"):
        create_playmakers_chat_client()


def test_exported_schemas_are_current() -> None:
    from playmakers_agents.contracts import AgentTraceEvent
    from playmakers_schema import models

    root = Path(models.__file__).parent / "schemas" / "v1"
    for model, name in ((OverlayCue, "overlay_cue"), (AgentTraceEvent, "agent_trace_event")):
        schema = json.loads((root / f"{name}.schema.json").read_text())
        expected = model.model_json_schema()
        assert all(schema[key] == value for key, value in expected.items())
    cue = OverlayCue(
        cue_id="test", clock_ms=0, template="test", payload={}, evidence_event_ids=["e1"]
    )
    validate(
        cue.model_dump(mode="json"), json.loads((root / "overlay_cue.schema.json").read_text())
    )


@pytest.mark.asyncio
async def test_mock_stream_and_non_stream_agree() -> None:
    client = DeterministicMockChatClient()
    prompt = Message(
        "user",
        [
            json.dumps(
                {
                    "event": passing().model_dump(mode="json"),
                    "kind": "tactics",
                    "metrics": {"difficulty": 0.6},
                    "evidence_event_ids": ["e1"],
                }
            )
        ],
    )
    normal = await client.get_response([prompt])
    streamed = await client.get_response([prompt], stream=True).get_final_response()
    assert streamed.text == normal.text


def test_live_client_selection_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent_framework_foundry
    import agent_framework_openai

    for name in ("AZURE_AI_PROJECT_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
        monkeypatch.delenv(name, raising=False)
    captured = {}

    def configured(**kwargs):
        captured.update(kwargs)
        return "configured"

    monkeypatch.setattr(agent_framework_openai, "OpenAIChatCompletionClient", configured)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "test-model")
    assert create_playmakers_chat_client() == "configured"
    assert captured["model"] == "test-model"
    assert captured["azure_endpoint"] == "https://example.invalid"
    assert "credential" in captured and "api_key" not in captured
    captured.clear()
    monkeypatch.setattr(agent_framework_foundry, "FoundryChatClient", configured)
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://project.invalid")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT", "foundry-model")
    assert create_playmakers_chat_client() == "configured"
    assert captured["project_endpoint"] == "https://project.invalid"
    assert captured["model"] == "foundry-model"


@pytest.mark.asyncio
async def test_cues_deterministic_across_runs() -> None:
    async def run():
        director = Director(client=DeterministicMockChatClient())
        cues = []
        for event in (passing(), passing(2, completed=False), shot()):
            cues.extend(cue.model_dump() for cue in await director.on_event(event))
        return cues

    assert await run() == await run()


@pytest.mark.asyncio
async def test_mcp_stats_agree_with_local_engine_for_every_event_type() -> None:
    from pitchsim.config import MatchConfig
    from pitchsim.sim import simulate_match

    events = simulate_match(MatchConfig(seed=7))[:60]
    assert {"pass", "shot", "carry", "tackle"} <= {event.event_type for event in events}
    async with serve(create_mcp().streamable_http_app()) as base_url:
        async with Director(
            client=DeterministicMockChatClient(),
            stats_mcp_url=base_url + "/mcp",
            whatif_rollouts=4,
        ) as director:
            for event in events:
                await director.on_event(event)
                stats_traces = [t for t in director.last_traces if t.agent == "stats"]
                assert [t.status for t in stats_traces] == ["ok"], event.event_type
