from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from starlette.types import ASGIApp


@asynccontextmanager
async def serve(app: ASGIApp) -> AsyncIterator[str]:
    """Run an actual HTTP transport in-process on an OS-assigned port."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Server failed to start")
                await asyncio.sleep(0.01)
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()
