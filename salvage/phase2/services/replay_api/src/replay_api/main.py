from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import FastAPI, WebSocket
from fastapi.responses import PlainTextResponse, StreamingResponse
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from pitchsim.config import MatchConfig
from pitchsim.replay import replay_events
from pitchsim.sim import simulate_match

from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.pipeline import PlaymakersPipeline, PlaymakersPipelineConfig
from stats_mcp.server import StatsMcpService

app = FastAPI(title="Playmakers Replay API", version="0.1.0")

_stats_service = StatsMcpService()
_stats_mcp = FastMCP(name="playmakers-stats", streamable_http_path="/mcp")


@_stats_mcp.tool()
def ingest_event(match_id: str, event: dict) -> dict:
    return _stats_service.ingest_event(match_id=match_id, event=event)


@_stats_mcp.tool()
def possession(match_id: str, match_clock_ms: int, window_ms: int = 120_000) -> dict:
    return _stats_service.possession(
        match_id=match_id, match_clock_ms=match_clock_ms, window_ms=window_ms
    )


@_stats_mcp.tool()
def pressure_index(
    match_id: str, team_id: str, match_clock_ms: int, window_ms: int = 60_000
) -> dict:
    return _stats_service.pressure_index(
        match_id=match_id, team_id=team_id, match_clock_ms=match_clock_ms, window_ms=window_ms
    )


@_stats_mcp.tool()
def pass_difficulty(match_id: str, event_id: str) -> dict:
    return _stats_service.pass_difficulty(match_id=match_id, event_id=event_id)


@_stats_mcp.tool()
def xg(match_id: str, event_id: str) -> dict:
    return _stats_service.xg(match_id=match_id, event_id=event_id)


@_stats_mcp.tool()
def momentum(match_id: str, match_clock_ms: int, window_ms: int = 180_000) -> dict:
    return _stats_service.momentum(
        match_id=match_id, match_clock_ms=match_clock_ms, window_ms=window_ms
    )


# Expose MCP tools from this same service process.
app.mount("/stats-mcp", _stats_mcp.streamable_http_app())


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


class PlaymakersReplayParams(BaseModel):
    seed: int = 0
    speed: float = 1.0
    persona: str = "analyst"
    language: str = "en"
    favorite_team_id: str | None = None
    favorite_player_id: str | None = None
    kill_tactics_after_sequence: int | None = None


async def _playmakers_sse_stream(params: PlaymakersReplayParams) -> AsyncGenerator[bytes, None]:
    cfg = MatchConfig(seed=params.seed)
    events = simulate_match(cfg)
    match_id = f"match_{params.seed}"

    profile = ViewerProfile(
        persona="casual" if params.persona == "casual" else "analyst",
        favorite_team_id=params.favorite_team_id,
        favorite_player_id=params.favorite_player_id,
        language="es" if params.language == "es" else "en",
    )
    pipeline = PlaymakersPipeline(
        match_id=match_id,
        config=PlaymakersPipelineConfig(
            profile=profile,
            checkpoint_dir=None,
            kill_tactics_after_sequence=params.kill_tactics_after_sequence,
            whatif_rollouts=60,
        ),
    )

    async for ev in replay_events(events, speed=params.speed):
        ev_dict = ev.model_dump(mode="json")
        _stats_service.ingest_event(match_id=match_id, event=ev_dict)

        # Emit the raw match event.
        yield b"event: match_event\n"
        yield b"data: " + json.dumps(ev_dict, separators=(",", ":")).encode("utf-8") + b"\n\n"

        # Run Playmakers pipeline and emit overlay cues.
        cues = await pipeline.on_event(ev)
        for cue in cues:
            cue_bytes = json.dumps(cue.model_dump(mode="json"), separators=(",", ":")).encode(
                "utf-8"
            )
            yield b"event: overlay_cue\n"
            yield b"data: " + cue_bytes + b"\n\n"


@app.get("/playmakers/sse")
async def playmakers_sse(
    seed: int = 0,
    speed: float = 1.0,
    persona: str = "analyst",
    language: str = "en",
    favorite_team_id: str | None = None,
    favorite_player_id: str | None = None,
    kill_tactics_after_sequence: int | None = None,
) -> StreamingResponse:
    params = PlaymakersReplayParams(
        seed=seed,
        speed=speed,
        persona=persona,
        language=language,
        favorite_team_id=favorite_team_id,
        favorite_player_id=favorite_player_id,
        kill_tactics_after_sequence=kill_tactics_after_sequence,
    )
    return StreamingResponse(
        _playmakers_sse_stream(params),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.websocket("/playmakers/ws")
async def playmakers_ws(
    ws: WebSocket,
    seed: int = 0,
    speed: float = 1.0,
    persona: str = "analyst",
    language: str = "en",
    favorite_team_id: str | None = None,
    favorite_player_id: str | None = None,
    kill_tactics_after_sequence: int | None = None,
) -> None:
    params = PlaymakersReplayParams(
        seed=seed,
        speed=speed,
        persona=persona,
        language=language,
        favorite_team_id=favorite_team_id,
        favorite_player_id=favorite_player_id,
        kill_tactics_after_sequence=kill_tactics_after_sequence,
    )
    await ws.accept()
    try:
        cfg = MatchConfig(seed=params.seed)
        events = simulate_match(cfg)
        match_id = f"match_{params.seed}"
        profile = ViewerProfile(
            persona="casual" if params.persona == "casual" else "analyst",
            favorite_team_id=params.favorite_team_id,
            favorite_player_id=params.favorite_player_id,
            language="es" if params.language == "es" else "en",
        )
        pipeline = PlaymakersPipeline(
            match_id=match_id,
            config=PlaymakersPipelineConfig(
                profile=profile,
                checkpoint_dir=None,
                kill_tactics_after_sequence=params.kill_tactics_after_sequence,
                whatif_rollouts=60,
            ),
        )
        async for ev in replay_events(events, speed=params.speed):
            ev_dict = ev.model_dump(mode="json")
            _stats_service.ingest_event(match_id=match_id, event=ev_dict)
            await ws.send_text(
                json.dumps({"type": "match_event", "data": ev_dict}, separators=(",", ":"))
            )
            cues = await pipeline.on_event(ev)
            for cue in cues:
                await ws.send_text(
                    json.dumps(
                        {"type": "overlay_cue", "data": cue.model_dump(mode="json")},
                        separators=(",", ":"),
                    )
                )
    finally:
        await ws.close()
