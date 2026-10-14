from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from gallery_agents.contracts import ViewerProfile
from gallery_agents.resilience import KillSpec
from gallery_agents.workflow import Director
from pitchsim.config import MatchConfig
from pitchsim.replay import replay_events
from pitchsim.sim import simulate_match
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
    async with stats_server.session_manager.run():
        yield


app = FastAPI(title="Gallery Replay API", version="0.2.0", lifespan=lifespan)
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


async def gallery_messages(
    seed: int, speed: float, profile: ViewerProfile, kill: str | None, whatif_rollouts: int
) -> AsyncGenerator[dict[str, Any], None]:
    events = await asyncio.to_thread(simulate_match, MatchConfig(seed=seed))
    async with Director(
        profiles=[profile], seed=seed, kill=kill, whatif_rollouts=whatif_rollouts
    ) as director:
        async for event in replay_events(events, speed=speed):
            yield {"type": "event", **event.model_dump(mode="json")}
            cues = await director.on_event(event)
            for trace in director.last_traces:
                yield {"type": "trace", **trace.model_dump(mode="json")}
            for cue in cues:
                yield {"type": "cue", **cue.model_dump(mode="json")}


@app.get("/gallery/sse")
async def gallery_sse(
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
        async for message in gallery_messages(seed, speed, profile, kill, whatif_rollouts):
            yield "data: " + json.dumps(message, separators=(",", ":")) + "\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.websocket("/gallery/ws")
async def gallery_ws(
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
        async for message in gallery_messages(seed, speed, profile, kill, whatif_rollouts):
            await ws.send_json(message)
    except WebSocketDisconnect:
        return
    else:
        await ws.close()
