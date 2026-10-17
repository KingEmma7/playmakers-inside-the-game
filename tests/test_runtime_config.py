from __future__ import annotations

import os
import sys
import types
from collections.abc import Mapping, Sequence
from typing import Any

import agent_framework.observability
import azure.identity
import azure.identity.aio
import pytest
from agent_framework import BaseChatClient, Message
from playmakers_agents import telemetry
from playmakers_agents.model_clients import (
    DeterministicMockChatClient,
    create_playmakers_chat_client,
    credential_options,
)
from playmakers_agents.what_if import rollout_workers
from playmakers_agents.workflow import DEFAULT_STATS_MCP_URL, Director
from replay_api import speech

ENV = (
    "PLAYMAKERS_AGENT_TIMEOUT_S",
    "PLAYMAKERS_TRANSLATION_TIMEOUT_S",
    "PLAYMAKERS_WHATIF_TIMEOUT_S",
    "STATS_MCP_URL",
    "AZURE_CLIENT_ID",
    "WHATIF_WORKERS",
    "APPLICATIONINSIGHTS_CONNECTION_STRING",
)


class OfflineLiveClient(BaseChatClient[Mapping[str, Any]]):
    """Stands in for a live model client; it is never called."""

    def _inner_get_response(self, *, messages: Sequence[Message], stream: bool, **kwargs: Any):
        raise AssertionError("no network in tests")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def wired(director: Director) -> tuple[float, float, float, float]:
    audience = director.workflow.executors["audience"]
    return (
        director.timeouts["tactics"],
        director.timeouts["storyline"],
        audience.timeout,
        director.what_if.explain_timeout,
    )


def test_timeouts_stay_tight_offline_and_widen_for_live_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert wired(Director(client=DeterministicMockChatClient())) == (4.0, 4.0, 1.5, 1.5)
    assert wired(Director(client=OfflineLiveClient())) == (8.0, 8.0, 3.0, 3.0)
    monkeypatch.setenv("PLAYMAKERS_AGENT_TIMEOUT_S", "12")
    monkeypatch.setenv("PLAYMAKERS_TRANSLATION_TIMEOUT_S", "2.5")
    monkeypatch.setenv("PLAYMAKERS_WHATIF_TIMEOUT_S", "5")
    assert wired(Director(client=OfflineLiveClient())) == (12.0, 12.0, 2.5, 5.0)
    explicit = Director(client=OfflineLiveClient(), timeouts={"tactics": 0.5})
    assert explicit.timeouts["tactics"] == 0.5
    assert explicit.timeouts["storyline"] == 12.0
    monkeypatch.setenv("PLAYMAKERS_AGENT_TIMEOUT_S", "0")
    with pytest.raises(ValueError, match="PLAYMAKERS_AGENT_TIMEOUT_S"):
        Director(client=OfflineLiveClient())


def test_live_stats_mcp_defaults_to_the_in_api_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DEFAULT_STATS_MCP_URL == "http://127.0.0.1:8000/stats-mcp/"
    assert Director(client=OfflineLiveClient()).stats_mcp_url == DEFAULT_STATS_MCP_URL
    assert Director(client=DeterministicMockChatClient()).stats_mcp_url is None
    monkeypatch.setenv("STATS_MCP_URL", "http://127.0.0.1:8765/mcp")
    assert Director(client=OfflineLiveClient()).stats_mcp_url == "http://127.0.0.1:8765/mcp"


def test_user_assigned_identity_is_selected_only_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_framework_foundry

    seen: list[dict[str, Any]] = []

    class Credential:
        def __init__(self, **kwargs: Any) -> None:
            seen.append(kwargs)

        def get_token(self, scope: str) -> Any:
            return types.SimpleNamespace(token="t")

    monkeypatch.setattr(azure.identity.aio, "DefaultAzureCredential", Credential)
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", Credential)
    monkeypatch.setattr(agent_framework_foundry, "FoundryChatClient", lambda **kw: kw)
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://project.invalid")
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT", "gpt-41-mini")
    # Passing managed_identity_client_id=None would force a system-assigned identity.
    assert credential_options() == {}
    create_playmakers_chat_client()
    assert seen[-1] == {}
    monkeypatch.setenv("AZURE_CLIENT_ID", "00000000-0000-0000-0000-000000000001")
    create_playmakers_chat_client()
    assert seen[-1] == {"managed_identity_client_id": "00000000-0000-0000-0000-000000000001"}
    assert speech.entra_token() == "t"
    assert seen[-1] == {"managed_identity_client_id": "00000000-0000-0000-0000-000000000001"}


def test_whatif_worker_count_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    assert 1 <= rollout_workers() <= 3
    monkeypatch.setenv("WHATIF_WORKERS", "1")
    assert rollout_workers() == 1
    monkeypatch.setenv("WHATIF_WORKERS", "0")
    with pytest.raises(ValueError, match="WHATIF_WORKERS"):
        rollout_workers()


def test_tracing_is_off_without_a_connection_string_and_wires_agent_framework_with_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    exporter = types.ModuleType("azure.monitor.opentelemetry")
    exporter.configure_azure_monitor = lambda **kw: calls.append(("azure_monitor", kw))
    monkeypatch.setitem(sys.modules, "azure.monitor.opentelemetry", exporter)
    monkeypatch.setattr(
        agent_framework.observability,
        "enable_instrumentation",
        lambda **kw: calls.append(("agent_framework", kw)),
    )
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setenv("OTEL_SERVICE_NAME", "unset")
    monkeypatch.delenv("OTEL_SERVICE_NAME")
    assert telemetry.configure_tracing() is False
    assert calls == []
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=test")
    assert telemetry.configure_tracing() is True
    assert calls == [
        ("azure_monitor", {"connection_string": "InstrumentationKey=test"}),
        ("agent_framework", {"enable_sensitive_data": True}),
    ]
    assert os.environ["OTEL_SERVICE_NAME"] == "playmakers-api"
    assert telemetry.configure_tracing() is True
    assert len(calls) == 2  # Configured once per process.
