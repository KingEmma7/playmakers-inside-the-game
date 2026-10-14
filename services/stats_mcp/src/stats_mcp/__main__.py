from __future__ import annotations

from stats_mcp.server import create_mcp

if __name__ == "__main__":
    create_mcp().run(transport="streamable-http")
