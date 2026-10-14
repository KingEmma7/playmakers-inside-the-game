from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI, WebSocket
from fastapi.responses import PlainTextResponse, StreamingResponse
from pitchsim.config import MatchConfig
from pitchsim.replay import replay_events
from pitchsim.sim import simulate_match

app = FastAPI(title="Gallery Replay API", version="0.1.0")


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
