from __future__ import annotations

import asyncio
import importlib
import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.workflow import Director
from replay_api import main as api
from test_stats import passing


@pytest.mark.asyncio
async def test_session_refcount_and_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    started = 0
    closed = 0
    release = asyncio.Event()

    async def producer(*args, **kwargs):
        nonlocal started, closed
        started += 1
        try:
            yield {"type": "event", "sequence": 1}
            await release.wait()
            yield {"type": "event", "sequence": 2}
        finally:
            closed += 1

    monkeypatch.setattr(api, "playmakers_messages", producer)
    profiles = [ViewerProfile(), ViewerProfile(persona="casual", language="es")]

    def subscribe(kill=None):
        return api.shared_messages(api.app, 7, 50, kill, 1, 0, profiles, profiles[0])

    async with subscribe() as first:
        async with subscribe() as second:
            assert await anext(first) == await anext(second)
            assert started == 1
        assert closed == 0
        async with subscribe("tactics@20") as different:
            await anext(different)
            assert started == 2
        assert closed == 1
        release.set()
        assert (await anext(first))["sequence"] == 2
    assert closed == 2
    assert not api._sessions


def test_two_http_streams_share_director_and_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a real socket: ASGI TestClient buffers streams until completion."""
    count = 0
    original = Director.__init__

    def counted(self, *args, **kwargs):
        nonlocal count
        count += 1
        original(self, *args, **kwargs)

    monkeypatch.setattr(Director, "__init__", counted)
    monkeypatch.setattr(
        api,
        "simulate_match",
        lambda _: [
            passing(1, clock=19 * 60000),
            passing(2, clock=20 * 60000),
            passing(3, clock=20 * 60000 + 1000),
        ],
    )

    async def paced(events, speed):
        for event in events:
            await asyncio.sleep(0.05)
            yield event

    monkeypatch.setattr(api, "replay_events", paced)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, lifespan="off", log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(0.01)

        async def run():
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:

                async def read(persona, language):
                    async with client.stream(
                        "GET",
                        "/playmakers/sse",
                        params={
                            "seed": 7,
                            "speed": 0,
                            "kill": "tactics@20",
                            "whatif_rollouts": 1,
                            "persona": persona,
                            "language": language,
                            "viewer_profiles": json.dumps(
                                [
                                    {"persona": "analyst", "language": "en"},
                                    {
                                        "persona": "casual",
                                        "language": "es",
                                        "favorite_player_id": "a",
                                    },
                                ]
                            ),
                        },
                    ) as response:
                        assert response.status_code == 200
                        return [
                            json.loads(line[6:])
                            async for line in response.aiter_lines()
                            if line.startswith("data: ")
                        ]

                return await asyncio.gather(read("analyst", "en"), read("casual", "es"))

        results = asyncio.run(run())
        assert count == 1
        for messages, persona in zip(results, ("analyst", "casual"), strict=True):
            assert {m["action"] for m in messages if m["type"] == "trace"} >= {
                "agent_down",
                "fallback_on",
                "restarted_from_checkpoint",
                "caught_up",
            }
            assert {m["persona"] for m in messages if m["type"] == "cue"} == {persona}
            assert len([m for m in messages if m["type"] == "event"]) == 3
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
    assert not thread.is_alive()
    assert not api._sessions


@pytest.mark.asyncio
async def test_periodic_checkpoint_restores_and_replays_tail(tmp_path: Path) -> None:
    async with Director(checkpoint_path=str(tmp_path)) as director:
        for sequence in range(1, 28):
            await director.on_event(passing(sequence, clock=sequence * 1000))
        assert director.writers[0].agent_sequences["test"] == 27
        saved = await director.recovery_storage.load("test")
        assert saved is not None
        assert saved.match.last_sequence == 25
        assert saved.agent_sequences["tactics"] == 25
    async with Director(checkpoint_path=str(tmp_path)) as restored:
        assert await restored.restore("test")
        for sequence in range(26, 29):
            assert await restored.on_event(passing(sequence, clock=sequence * 1000))
        assert restored.writers[0].agent_sequences["test"] == 28
        assert len(restored.store.get_or_create("test").events) == 28


def test_cors_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://demo.example, https://other.example")
    try:
        module = importlib.reload(api)
        with TestClient(module.app) as client:
            allowed = client.get("/healthz", headers={"Origin": "https://other.example"})
            assert allowed.headers["access-control-allow-origin"] == "https://other.example"
            denied = client.get("/healthz", headers={"Origin": "http://localhost:5173"})
            assert "access-control-allow-origin" not in denied.headers
    finally:
        monkeypatch.delenv("CORS_ORIGINS")
        importlib.reload(api)


def test_websocket_forwards_replay_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    async def messages(*args, **kwargs):
        assert kwargs["replay_from_ms"] == 1_200_000
        yield {"type": "event", "sequence": 1}

    monkeypatch.setattr(api, "playmakers_messages", messages)
    with TestClient(api.app) as client:
        with client.websocket_connect("/playmakers/ws?replay_from_ms=1200000") as ws:
            assert ws.receive_json() == {"type": "event", "sequence": 1}


def test_invalid_viewer_lists_are_rejected() -> None:
    with TestClient(api.app) as client:
        for profiles in (
            {},
            [],
            [None],
            [{"persona": "unknown"}],
            [
                {"persona": "analyst", "language": "en"},
                {"persona": "analyst", "language": "en"},
            ],
        ):
            assert (
                client.get(
                    "/playmakers/sse", params={"viewer_profiles": json.dumps(profiles)}
                ).status_code
                == 422
            )
