from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from concurrent.futures import ProcessPoolExecutor
from contextlib import aclosing, asynccontextmanager, suppress
from typing import Annotated, Any, Literal

from anyio import CancelScope
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pitchsim.config import MatchConfig
from pitchsim.replay import replay_events
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import AgentTraceEvent, OverlayCue, ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient, live_model_configured
from playmakers_agents.resilience import KillSpec
from playmakers_agents.telemetry import configure_tracing
from playmakers_agents.what_if import create_rollout_pool
from playmakers_agents.workflow import Director
from playmakers_schema.models import MatchEvent
from pydantic import TypeAdapter
from starlette.routing import Mount
from stats_mcp.server import create_mcp

from replay_api.ask import router as ask_router
from replay_api.limits import LiveMatchBudget
from replay_api.speech import router as speech_router

live_budget = LiveMatchBudget.from_env()


def _whatif_pool(app: FastAPI) -> ProcessPoolExecutor | None:
    pool = getattr(app.state, "whatif_pool", None)
    if pool is not None and getattr(pool, "_broken", False):
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        pool = create_rollout_pool()
        app.state.whatif_pool = pool
    return pool


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # MCP 1.x session managers are single-use: build one per application lifespan.
    stats_server = create_mcp(path="/")
    stats_app = stats_server.streamable_http_app()
    for route in app.routes:
        if isinstance(route, Mount) and route.path == "/stats-mcp":
            route.app = stats_app
    pool = create_rollout_pool()
    app.state.whatif_pool = pool
    try:
        async with stats_server.session_manager.run():
            yield
    finally:
        await asyncio.to_thread(pool.shutdown, wait=True, cancel_futures=True)
        app.state.whatif_pool = None


configure_tracing()
app = FastAPI(title="Playmakers Replay API", version="0.2.0", lifespan=lifespan)
app.state.whatif_pool = None
app.mount("/stats-mcp", FastAPI())
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        s.strip()
        for s in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if s.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


app.include_router(speech_router)
app.include_router(ask_router)


@app.get("/healthz")
def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/model/config")
def model_config() -> dict[str, bool]:
    """Lets the UI label mock-model timings honestly; a capped live match also says so in-stream."""
    return {"live": live_model_configured()}


async def _sse_stream(seed: int, speed: float) -> AsyncGenerator[bytes, None]:
    events = simulate_match(MatchConfig(seed=seed))
    async for ev in replay_events(events, speed=speed):
        payload = json.dumps(ev.model_dump(mode="json"), separators=(",", ":")).encode("utf-8")
        yield b"event: match_event\n"
        yield b"data: " + payload + b"\n\n"


@app.get("/replay/sse")
async def replay_sse(
    seed: Annotated[int, Query(ge=0, le=10_000)] = 0,
    speed: Annotated[float, Query(ge=0, le=100)] = 1.0,
) -> StreamingResponse:
    return StreamingResponse(
        _sse_stream(seed=seed, speed=speed),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.websocket("/replay/ws")
async def replay_ws(
    ws: WebSocket,
    seed: Annotated[int, Query(ge=0, le=10_000)] = 0,
    speed: Annotated[float, Query(ge=0, le=100)] = 1.0,
) -> None:
    await ws.accept()
    try:
        events = simulate_match(MatchConfig(seed=seed))
        async for ev in replay_events(events, speed=speed):
            await ws.send_text(json.dumps(ev.model_dump(mode="json"), separators=(",", ":")))
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError:
        raise
    else:
        await ws.close()


async def playmakers_messages(
    seed: int,
    speed: float,
    profile: ViewerProfile,
    kill: str | None,
    whatif_rollouts: int,
    replay_from_ms: int = 0,
    whatif_pool: ProcessPoolExecutor | None = None,
    profiles: list[ViewerProfile] | None = None,
    budget: LiveMatchBudget | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    budget = budget or live_budget
    live = live_model_configured()
    offline_reason = budget.acquire() if live else None
    holds_slot = live and offline_reason is None
    try:
        async for message in _director_messages(
            seed,
            speed,
            profile,
            kill,
            whatif_rollouts,
            replay_from_ms,
            whatif_pool,
            profiles,
            offline_reason,
        ):
            yield message
    finally:
        if holds_slot:
            budget.release()


async def _director_messages(
    seed: int,
    speed: float,
    profile: ViewerProfile,
    kill: str | None,
    whatif_rollouts: int,
    replay_from_ms: int,
    whatif_pool: ProcessPoolExecutor | None,
    profiles: list[ViewerProfile] | None,
    offline_reason: str | None,
) -> AsyncGenerator[dict[str, Any], None]:
    events = await asyncio.to_thread(simulate_match, MatchConfig(seed=seed))
    async with Director(
        profiles=profiles or [profile],
        seed=seed,
        kill=kill,
        whatif_rollouts=whatif_rollouts,
        whatif_pool=whatif_pool,
        client=DeterministicMockChatClient() if offline_reason else None,
    ) as director:
        if offline_reason:
            yield {"type": "status", "model": "offline", "reason": offline_reason}

        async def paced_events() -> AsyncGenerator[Any, None]:
            # Rebuild the exact deterministic prefix quickly on a failure-injection replay.
            split = next(
                (i for i, e in enumerate(events) if e.clock_ms >= replay_from_ms), len(events)
            )
            async for event in replay_events(events[:split], speed=0):
                yield event
            async for event in replay_events(events[split:], speed=speed):
                yield event

        async for event in paced_events():
            async with aclosing(_event_messages(director, event)) as messages:
                async for message in messages:
                    yield message


async def _event_messages(
    director: Director, event: MatchEvent
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream checked captions first, then simulations, cancelling work on disconnect."""
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    published_cues = 0
    published_traces = 0

    async def publish(cues: list[OverlayCue], traces: list[AgentTraceEvent]) -> None:
        nonlocal published_cues, published_traces
        # Publish the clock/score and its checked captions together, before rollouts.
        queue.put_nowait({"type": "event", **event.model_dump(mode="json")})
        for trace in traces:
            queue.put_nowait({"type": "trace", **trace.model_dump(mode="json")})
        for cue in cues:
            queue.put_nowait({"type": "cue", **cue.model_dump(mode="json")})
        published_cues, published_traces = len(cues), len(traces)

    async def produce() -> None:
        try:
            cues = await director.on_event(event, publish=publish)
            for trace in director.last_traces[published_traces:]:
                queue.put_nowait({"type": "trace", **trace.model_dump(mode="json")})
            for cue in cues[published_cues:]:
                queue.put_nowait({"type": "cue", **cue.model_dump(mode="json")})
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(produce())
    try:
        while (message := await queue.get()) is not None:
            yield message
        await task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


class MatchSession:
    """One producer, bounded-by-match history, and independent subscriber cursors."""

    def __init__(self, messages: AsyncGenerator[dict[str, Any], None]) -> None:
        self.messages = messages
        self.history: list[dict[str, Any]] = []
        self.changed = asyncio.Condition()
        self.subscribers = 0
        self.done = False
        self.error: Exception | None = None
        self.task = asyncio.create_task(self.run())

    async def run(self) -> None:
        try:
            async with aclosing(self.messages):
                async for message in self.messages:
                    async with self.changed:
                        self.history.append(message)
                        self.changed.notify_all()
        except Exception as exc:
            self.error = exc
        finally:
            async with self.changed:
                self.done = True
                self.changed.notify_all()

    async def subscribe(self, profile: ViewerProfile) -> AsyncGenerator[dict[str, Any], None]:
        cursor = 0
        while True:
            async with self.changed:
                await self.changed.wait_for(
                    lambda cursor=cursor: cursor < len(self.history) or self.done
                )
                batch = self.history[cursor:]
                cursor = len(self.history)
                done = self.done
            for message in batch:
                if message["type"] != "cue" or (
                    message["persona"] == profile.persona
                    and message["language"] == profile.language
                ):
                    yield message
            if done:
                if self.error:
                    raise self.error
                return


# Entries are removed on the last disconnect, including completed sessions.
_sessions: dict[tuple[Any, ...], MatchSession] = {}


@asynccontextmanager
async def shared_messages(
    application: FastAPI,
    seed: int,
    speed: float,
    kill: str | None,
    whatif_rollouts: int,
    replay_from_ms: int,
    profiles: list[ViewerProfile],
    profile: ViewerProfile,
) -> AsyncGenerator[AsyncGenerator[dict[str, Any], None], None]:
    key = (
        id(application),
        seed,
        speed,
        kill,
        whatif_rollouts,
        replay_from_ms,
        tuple(p.model_dump_json() for p in profiles),
    )
    session = _sessions.get(key)
    if session is None:
        session = MatchSession(
            playmakers_messages(
                seed,
                speed,
                profile,
                kill,
                whatif_rollouts,
                replay_from_ms,
                whatif_pool=_whatif_pool(application),
                profiles=profiles,
            )
        )
        _sessions[key] = session
    session.subscribers += 1
    try:
        async with aclosing(session.subscribe(profile)) as messages:
            yield messages
    finally:
        session.subscribers -= 1
        if not session.subscribers:
            _sessions.pop(key, None)
            session.task.cancel()
            # StreamingResponse may finalize inside an already-cancelled AnyIO scope.
            with CancelScope(shield=True):
                await asyncio.gather(session.task, return_exceptions=True)


@app.get("/playmakers/sse")
async def playmakers_sse(
    request: Request,
    viewer_profiles: str | None = None,
    replay_from_ms: Annotated[int, Query(ge=0, le=5_400_000)] = 0,
    seed: Annotated[int, Query(ge=0, le=10_000)] = 7,
    speed: Annotated[float, Query(ge=0, le=100)] = 50,
    persona: Literal["analyst", "casual"] = "analyst",
    language: Literal["en", "es", "fr"] = "en",
    favourite_team_id: str | None = None,
    favourite_player_id: str | None = None,
    kill: str | None = None,
    whatif_rollouts: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> StreamingResponse:
    try:
        KillSpec.parse(kill)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    profile = ViewerProfile(
        persona=persona,
        language=language,
        favorite_team_id=favourite_team_id,
        favorite_player_id=favourite_player_id,
    )

    try:
        profiles = (
            TypeAdapter(list[ViewerProfile]).validate_json(viewer_profiles)
            if viewer_profiles
            else [
                ViewerProfile(persona=p, language=lang)
                for p in ("analyst", "casual")
                for lang in ("en", "es", "fr")
            ]
        )
        if viewer_profiles:
            selected = next(
                (p for p in profiles if (p.persona, p.language) == (persona, language)), None
            )
            if selected is None:
                raise ValueError("Requested profile must be in viewer_profiles")
            profile = selected
        else:
            profiles = [
                profile if (p.persona, p.language) == (persona, language) else p for p in profiles
            ]
        if not 1 <= len(profiles) <= 8:
            raise ValueError("Supply 1–8 viewer profiles")
        if len({(p.persona, p.language) for p in profiles}) != len(profiles):
            raise ValueError("Each persona/language pair must be unique")
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid viewer_profiles") from exc

    async def stream() -> AsyncGenerator[str, None]:
        async with shared_messages(
            request.app, seed, speed, kill, whatif_rollouts, replay_from_ms, profiles, profile
        ) as messages:
            async for message in messages:
                yield "data: " + json.dumps(message, separators=(",", ":")) + "\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/playmakers/ws")
async def playmakers_ws(
    ws: WebSocket,
    replay_from_ms: Annotated[int, Query(ge=0, le=5_400_000)] = 0,
    seed: Annotated[int, Query(ge=0, le=10_000)] = 7,
    speed: Annotated[float, Query(ge=0, le=100)] = 50,
    persona: Literal["analyst", "casual"] = "analyst",
    language: Literal["en", "es", "fr"] = "en",
    favourite_team_id: str | None = None,
    favourite_player_id: str | None = None,
    kill: str | None = None,
    whatif_rollouts: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> None:
    try:
        KillSpec.parse(kill)
    except ValueError:
        await ws.close(code=1008)
        return
    profile = ViewerProfile(
        persona=persona,
        language=language,
        favorite_team_id=favourite_team_id,
        favorite_player_id=favourite_player_id,
    )
    await ws.accept()
    try:
        async with aclosing(
            playmakers_messages(
                seed,
                speed,
                profile,
                kill,
                whatif_rollouts,
                replay_from_ms=replay_from_ms,
                whatif_pool=_whatif_pool(ws.app),
            )
        ) as messages:
            async for message in messages:
                await ws.send_json(message)
    except WebSocketDisconnect:
        return
    else:
        await ws.close()
