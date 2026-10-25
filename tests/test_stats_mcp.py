from __future__ import annotations

import json

import pytest
from conftest import serve
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from stats_mcp.server import StatsMcpService, create_mcp
from test_stats import passing


@pytest.mark.asyncio
@pytest.mark.parametrize("mounted", [False, True])
async def test_real_streamable_http_tools(mounted: bool) -> None:
    if mounted:
        from replay_api.main import app

        path = "/stats-mcp/"
    else:
        app = create_mcp().streamable_http_app()
        path = "/mcp"
    async with serve(app) as base_url:
        async with streamable_http_client(base_url + path) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {
                    "ingest_event",
                    "possession",
                    "pressure_index",
                    "pass_difficulty",
                    "xg",
                    "momentum",
                    "control_vs_chaos",
                    "goal_threat",
                }
                event = passing().model_dump(mode="json")
                result = await session.call_tool(
                    "ingest_event", {"match_id": "test", "event": event}
                )
                assert not result.isError
                result = await session.call_tool(
                    "possession", {"match_id": "test", "match_clock_ms": 1000}
                )
                assert not result.isError
                data = result.structuredContent or json.loads(result.content[0].text)
                assert data["home_possession"] == 1
                assert data["evidence"]["event_ids"] == ["e1"]
                result = await session.call_tool(
                    "control_vs_chaos",
                    {
                        "match_id": "test",
                        "team_id": "TEST_HOME",
                        "match_clock_ms": 1000,
                    },
                )
                assert not result.isError
                assert result.structuredContent["turnover_rate"] == 0
                result = await session.call_tool(
                    "goal_threat",
                    {"match_id": "test", "team_id": "TEST_HOME", "match_clock_ms": 1000},
                )
                assert not result.isError
                assert result.structuredContent["evidence"]["event_ids"] == ["e1"]
                assert 0 < result.structuredContent["probability"] < 1
                assert result.structuredContent["horizon_ms"] == 120_000
                result = await session.call_tool("xg", {"match_id": "test", "event_id": "e1"})
                assert result.isError


def test_service_validates_union_and_match() -> None:
    service = StatsMcpService()
    with pytest.raises(ValueError):
        service.ingest_event("other", passing().model_dump(mode="json"))
    service.ingest_event("test", passing().model_dump(mode="json"))
    assert service.possession("other", 1000).evidence.event_ids == []
