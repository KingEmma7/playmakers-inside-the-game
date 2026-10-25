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


@pytest.mark.asyncio
async def test_goal_captions_stream_before_slow_whatif(monkeypatch: pytest.MonkeyPatch) -> None:
    from pitchsim.config import MatchConfig
    from pitchsim.sim import simulate_match
    from playmakers_agents.what_if import WhatIfAgent

    goal = next(e for e in simulate_match(MatchConfig(seed=382)) if e.event_type == "goal")
    monkeypatch.setattr(api, "simulate_match", lambda _: [goal])
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_rollouts(self, events):
        entered.set()
        await release.wait()
        return None

    monkeypatch.setattr(WhatIfAgent, "evaluate", slow_rollouts)
    profiles = [ViewerProfile(), ViewerProfile(persona="casual")]
    messages = api._director_messages(382, 0, profiles[0], None, 4, 0, None, profiles, None)
    try:
        event = await asyncio.wait_for(anext(messages), 5)
        assert event["type"] == "event"
        assert event["event_id"] == goal.event_id
        captions = []
        while len(captions) < 4:
            message = await asyncio.wait_for(anext(messages), 5)
            if message["type"] == "cue":
                captions.append(message)
        await asyncio.wait_for(entered.wait(), 5)
        assert not release.is_set()
        assert {c["persona"] for c in captions} == {"analyst", "casual"}
        assert all(c["payload"]["headline"].startswith("GOAL,") for c in captions)
        assert all(c["clock_ms"] == goal.clock_ms for c in captions)
        assert all(c["provenance"]["compliance"] == "verified" for c in captions)
        release.set()
        assert [m async for m in messages] == []  # No duplicate primary cues or traces.
    finally:
        release.set()
        await messages.aclose()


@pytest.mark.asyncio
async def test_closing_event_stream_cancels_pending_rollouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async with Director(checkpoint_path=str(tmp_path)) as director:

        async def stalled(events):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(director.what_if, "evaluate", stalled)
        messages = api._event_messages(director, passing())
        assert (await anext(messages))["type"] == "event"
        await entered.wait()
        await messages.aclose()
        assert cancelled.is_set()


@pytest.mark.asyncio
async def test_pace_and_language_keep_one_live_budget_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    from replay_api.limits import LiveMatchBudget

    budget = LiveMatchBudget(2, 15)
    monkeypatch.setattr(api, "live_budget", budget)
    monkeypatch.setattr(api, "live_model_configured", lambda: True)
    release = asyncio.Event()
    starts = 0

    async def director(*args):
        nonlocal starts
        starts += 1
        yield {"type": "event", "sequence": 1}
        await release.wait()
        yield {"type": "event", "sequence": 2}

    monkeypatch.setattr(api, "_director_messages", director)
    profiles = [ViewerProfile(), ViewerProfile(persona="casual", language="es")]

    def subscribe(profile, speed=10):
        return api.shared_messages(
            api.app, 7, speed, None, 1, 0, profiles, profile, session_id="test-session"
        )

    async with subscribe(profiles[0]) as analyst:
        assert (await anext(analyst))["sequence"] == 1
        session = next(iter(api._sessions.values()))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/playmakers/pace", params={"session_id": "test-session", "speed": 50}
            )
            assert response.status_code == 200
            assert session.pace is not None and session.pace.speed == 50
        async with subscribe(profiles[1], speed=50) as spanish:
            assert (await anext(spanish))["sequence"] == 1
            assert next(iter(api._sessions.values())) is session
            release.set()
            assert (await anext(analyst))["sequence"] == 2
            assert (await anext(spanish))["sequence"] == 2
        assert starts == 1
        assert budget.started_today == 1
    assert budget.active == 0
    assert not api._sessions


@pytest.mark.asyncio
async def test_pace_change_wakes_current_delay() -> None:
    pace = api.ReplayPace(1)
    waiting = asyncio.create_task(pace.wait(60))
    await asyncio.sleep(0)
    pace.set_speed(0)
    await asyncio.wait_for(waiting, 0.1)


def test_pace_requires_valid_connected_session() -> None:
    with TestClient(api.app) as client:
        assert client.post("/playmakers/pace?session_id=missing&speed=50").status_code == 404
        assert client.post("/playmakers/pace?session_id=missing&speed=101").status_code == 422


@pytest.mark.asyncio
async def test_all_language_subscription_filters_persona() -> None:
    async def messages():
        yield {"type": "event", "sequence": 1}
        for persona in ("analyst", "casual"):
            for language in ("en", "es", "fr"):
                yield {"type": "cue", "persona": persona, "language": language}

    session = api.MatchSession(messages())
    profile = ViewerProfile(persona="casual")
    received = [m async for m in session.subscribe(profile, all_languages=True)]
    assert received[0]["type"] == "event"
    assert [m["language"] for m in received[1:]] == ["en", "es", "fr"]
    assert all(m["persona"] == "casual" for m in received[1:])
    english = [m async for m in session.subscribe(profile)]
    assert len(english) == 2 and english[1]["language"] == "en"
    await session.task
