from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

from stats_mcp.server import StatsMcpService


def main() -> None:
    parser = argparse.ArgumentParser(prog="stats-mcp")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=43124)
    args = parser.parse_args()

    service = StatsMcpService()
    mcp = FastMCP(name="gallery-stats", host=args.host, port=args.port, streamable_http_path="/mcp")

    @mcp.tool()
    def ingest_event(match_id: str, event: dict) -> dict:
        return service.ingest_event(match_id=match_id, event=event)

    @mcp.tool()
    def possession(match_id: str, match_clock_ms: int, window_ms: int = 120_000) -> dict:
        return service.possession(
            match_id=match_id, match_clock_ms=match_clock_ms, window_ms=window_ms
        )

    @mcp.tool()
    def pressure_index(
        match_id: str, team_id: str, match_clock_ms: int, window_ms: int = 60_000
    ) -> dict:
        return service.pressure_index(
            match_id=match_id, team_id=team_id, match_clock_ms=match_clock_ms, window_ms=window_ms
        )

    @mcp.tool()
    def pass_difficulty(match_id: str, event_id: str) -> dict:
        return service.pass_difficulty(match_id=match_id, event_id=event_id)

    @mcp.tool()
    def xg(match_id: str, event_id: str) -> dict:
        return service.xg(match_id=match_id, event_id=event_id)

    @mcp.tool()
    def momentum(match_id: str, match_clock_ms: int, window_ms: int = 180_000) -> dict:
        return service.momentum(
            match_id=match_id, match_clock_ms=match_clock_ms, window_ms=window_ms
        )

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
