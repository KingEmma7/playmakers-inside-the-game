from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from gallery_schema.models import MatchEvent


async def replay_events(
    events: list[MatchEvent],
    *,
    speed: float = 1.0,
) -> AsyncGenerator[MatchEvent, None]:
    """
    Replay a pre-simulated event list over time.

    - speed=1.0: real time
    - speed=10.0: 10x faster
    - speed<=0: no waiting (emit as fast as possible)
    """
    if speed <= 0:
        for e in events:
            yield e
        return

    last_ms = None
    for e in events:
        clock_ms = e.clock_ms  # type: ignore[attr-defined]
        if last_ms is not None:
            dt_ms = max(0, clock_ms - last_ms)
            await asyncio.sleep((dt_ms / 1000.0) / speed)
        last_ms = clock_ms
        yield e
