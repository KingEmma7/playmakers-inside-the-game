from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from concurrent.futures import ProcessPoolExecutor
from contextlib import aclosing, asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pitchsim.config import MatchConfig
from pitchsim.replay import replay_events
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.resilience import KillSpec
from playmakers_agents.what_if import create_rollout_pool
from playmakers_agents.workflow import Director
from starlette.routing import Mount
from stats_mcp.server import create_mcp


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


app = FastAPI(title="Playmakers Replay API", version="0.2.0", lifespan=lifespan)
app.mount("/stats-mcp", FastAPI())
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


async def _sse_stream(seed: int, speed: float) -> AsyncGenerator[bytes, None]:
    events = simulate_match(MatchConfig(seed=seed))
    async for ev in replay_events(events, speed=speed):
        payload = json.dumps(ev.model_dump(mode="json"), separators=(",", ":")).encode("utf-8")
        yield b"event: match_event\n"
        yield b"data: " + payload + b"\n\n"


@app.get("/replay/sse")
async def replay_sse(seed: int = 0, speed: float = 1.0) -> StreamingResponse:
    return StreamingResponse(
        _sse_stream(seed=seed, speed=speed),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.websocket("/replay/ws")
async def replay_ws(ws: WebSocket, seed: int = 0, speed: float = 1.0) -> None:
    await ws.accept()
    try:
        events = simulate_match(MatchConfig(seed=seed))
        async for ev in replay_events(events, speed=speed):
            await ws.send_text(json.dumps(ev.model_dump(mode="json"), separators=(",", ":")))
    except asyncio.CancelledError:
        raise
    finally:
        await ws.close()


async def playmakers_messages(
    seed: int,
    speed: float,
    profile: ViewerProfile,
    kill: str | None,
    whatif_rollouts: int,
    replay_from_ms: int = 0,
    whatif_pool: ProcessPoolExecutor | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    events = await asyncio.to_thread(simulate_match, MatchConfig(seed=seed))
    async with Director(
        profiles=[profile],
        seed=seed,
        kill=kill,
        whatif_rollouts=whatif_rollouts,
        whatif_pool=whatif_pool,
    ) as director:

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
            yield {"type": "event", **event.model_dump(mode="json")}
            cues = await director.on_event(event)
            for trace in director.last_traces:
                yield {"type": "trace", **trace.model_dump(mode="json")}
            for cue in cues:
                yield {"type": "cue", **cue.model_dump(mode="json")}


@app.get("/playmakers/sse")
async def playmakers_sse(
    request: Request,
    replay_from_ms: Annotated[int, Query(ge=0, le=5_400_000)] = 0,
    seed: int = 7,
    speed: float = 50,
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

    async def stream() -> AsyncGenerator[str, None]:
        # Closing the wrapper must also close the Director if suspended at a yield.
        async with aclosing(
            playmakers_messages(
                seed,
                speed,
                profile,
                kill,
                whatif_rollouts,
                replay_from_ms,
                whatif_pool=request.app.state.whatif_pool,
            )
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
    seed: int = 7,
    speed: float = 50,
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
                whatif_pool=ws.app.state.whatif_pool,
            )
        ) as messages:
            async for message in messages:
                await ws.send_json(message)
    except WebSocketDisconnect:
        return
    else:
        await ws.close()
