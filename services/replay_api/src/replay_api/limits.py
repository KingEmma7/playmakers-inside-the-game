from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime

from fastapi import Request


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    value = int(raw) if raw else default
    if value < 0:
        raise ValueError(f"{name} must be zero or more")
    return value


def utc_today() -> date:
    return datetime.now(UTC).date()


class LiveMatchBudget:
    """Caps live-model matches so a public demo cannot run up the model bill.

    A refused match still plays, on the deterministic offline crew.
    """

    def __init__(
        self, max_concurrent: int, daily: int, today: Callable[[], date] = utc_today
    ) -> None:
        self.max_concurrent, self.daily, self.today = max_concurrent, daily, today
        self.active = 0
        self.day = today()
        self.started_today = 0

    @classmethod
    def from_env(cls) -> LiveMatchBudget:
        return cls(
            _env_int("PLAYMAKERS_MAX_LIVE_MATCHES", 2),
            _env_int("PLAYMAKERS_DAILY_LIVE_MATCHES", 15),
        )

    def acquire(self) -> str | None:
        """Return None when a live slot is granted, otherwise the reason for going offline."""
        if (day := self.today()) != self.day:
            self.day, self.started_today = day, 0
        if self.started_today >= self.daily:
            return "daily_cap"
        if self.active >= self.max_concurrent:
            return "busy"
        self.active += 1
        self.started_today += 1
        return None

    def release(self) -> None:
        self.active = max(0, self.active - 1)


class AskBudget:
    """Independent per-process model-call allowance, reset at midnight UTC."""

    def __init__(self, daily: int, today: Callable[[], date] = utc_today) -> None:
        self.daily, self.today = daily, today
        self.day, self.used = today(), 0

    @classmethod
    def from_env(cls) -> AskBudget:
        return cls(_env_int("PLAYMAKERS_DAILY_ASK_MODEL_CALLS", 60))

    def acquire(self) -> bool:
        if (day := self.today()) != self.day:
            self.day, self.used = day, 0
        if self.used >= self.daily:
            return False
        self.used += 1
        return True


class RateLimiter:
    """Sliding-window limit per client plus an overall ceiling across all clients."""

    def __init__(
        self,
        per_client: int,
        total: int,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_client, self.total, self.window_s, self.clock = per_client, total, window_s, clock
        self.clients: dict[str, deque[float]] = {}
        self.overall: deque[float] = deque()

    @classmethod
    def for_speech(cls) -> RateLimiter:
        return cls(
            _env_int("PLAYMAKERS_SPEECH_PER_MINUTE", 40),
            _env_int("PLAYMAKERS_SPEECH_TOTAL_PER_MINUTE", 120),
        )

    def allow(self, client: str) -> bool:
        now = self.clock()
        cutoff = now - self.window_s
        for key in list(self.clients):
            hits = self.clients[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del self.clients[key]
        while self.overall and self.overall[0] <= cutoff:
            self.overall.popleft()
        hits = self.clients.setdefault(client, deque())
        if len(hits) >= self.per_client or len(self.overall) >= self.total:
            return False
        hits.append(now)
        self.overall.append(now)
        return True


def client_key(request: Request) -> str:
    # Container Apps ingress appends the caller's address, so the last hop is the trusted one.
    forwarded = request.headers.get("x-forwarded-for", "")
    if hops := [hop.strip() for hop in forwarded.split(",") if hop.strip()]:
        return hops[-1]
    return request.client.host if request.client else "unknown"
