from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from playmakers_agents.contracts import ViewerProfile
from replay_api import main as api
from replay_api import speech
from replay_api.limits import LiveMatchBudget, RateLimiter

LIVE_ENV = {
    "AZURE_AI_PROJECT_ENDPOINT": "https://project.invalid",
    "AZURE_AI_MODEL_DEPLOYMENT": "m",
}


def test_live_budget_caps_concurrent_and_daily_matches() -> None:
    day = [date(2026, 10, 27)]
    budget = LiveMatchBudget(max_concurrent=2, daily=3, today=lambda: day[0])
    assert budget.acquire() is None
    assert budget.acquire() is None
    assert budget.acquire() == "busy"
    budget.release()
    assert budget.acquire() is None
    budget.release()
    assert budget.acquire() == "daily_cap"
    day[0] = date(2026, 10, 28)
    assert budget.acquire() is None
    assert budget.active == 2


def test_live_budget_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAYMAKERS_MAX_LIVE_MATCHES", raising=False)
    monkeypatch.delenv("PLAYMAKERS_DAILY_LIVE_MATCHES", raising=False)
    budget = LiveMatchBudget.from_env()
    assert (budget.max_concurrent, budget.daily) == (2, 15)
    monkeypatch.setenv("PLAYMAKERS_MAX_LIVE_MATCHES", "-1")
    with pytest.raises(ValueError, match="PLAYMAKERS_MAX_LIVE_MATCHES"):
        LiveMatchBudget.from_env()


async def first_messages(budget: LiveMatchBudget, count: int) -> list[dict]:
    messages = api.playmakers_messages(
        7, 0, ViewerProfile(), None, 2, profiles=[ViewerProfile()], budget=budget
    )
    seen = []
    async for message in messages:
        seen.append(message)
        if len(seen) == count:
            break
    await messages.aclose()
    return seen


@pytest.mark.asyncio
async def test_capped_live_match_falls_back_to_the_offline_crew_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in LIVE_ENV.items():
        monkeypatch.setenv(name, value)
    budget = LiveMatchBudget(max_concurrent=0, daily=15)
    messages = await first_messages(budget, 20)
    assert messages[0] == {"type": "status", "model": "offline", "reason": "busy"}
    assert messages[1]["type"] == "event"
    cues = [m for m in messages if m["type"] == "cue"]
    assert cues and cues[0]["provenance"]["compliance"] == "verified"
    assert budget.active == 0
    exhausted = LiveMatchBudget(max_concurrent=2, daily=0)
    assert (await first_messages(exhausted, 1))[0]["reason"] == "daily_cap"


@pytest.mark.asyncio
async def test_offline_default_needs_no_budget_and_sends_no_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (*LIVE_ENV, "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
        monkeypatch.delenv(name, raising=False)
    budget = LiveMatchBudget(max_concurrent=0, daily=0)
    messages = await first_messages(budget, 3)
    assert [m["type"] for m in messages][0] == "event"
    assert budget.started_today == 0


def test_rate_limiter_window_per_client_and_overall() -> None:
    now = [0.0]
    limiter = RateLimiter(per_client=2, total=3, window_s=60, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")
    assert not limiter.allow("c")  # Overall ceiling across clients.
    now[0] = 61
    assert limiter.allow("a") and limiter.allow("c")
    assert set(limiter.clients) == {"a", "c"}


def test_speech_route_is_rate_limited_per_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_SPEECH_REGION", "AZURE_SPEECH_RESOURCE_ID", "AZURE_SPEECH_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(speech, "limiter", RateLimiter(per_client=2, total=100))
    client = TestClient(api.app)
    headers = {"X-Playmakers-Speech": "1", "X-Forwarded-For": "203.0.113.9, 198.51.100.7"}
    statuses = [
        client.get("/speech/synthesize", params={"text": "Goal"}, headers=headers).status_code
        for _ in range(3)
    ]
    assert statuses == [503, 503, 429]
    other = {"X-Playmakers-Speech": "1", "X-Forwarded-For": "198.51.100.8"}
    assert (
        client.get("/speech/synthesize", params={"text": "Goal"}, headers=other).status_code == 503
    )


@pytest.mark.asyncio
async def test_live_slot_is_held_while_streaming_and_released_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in LIVE_ENV.items():
        monkeypatch.setenv(name, value)
    budget = LiveMatchBudget(max_concurrent=1, daily=15)
    seen_reasons = []

    async def fake_director(*args):
        seen_reasons.append(args[-1])
        yield {"type": "event", "active": budget.active}
        yield {"type": "event", "active": budget.active}

    monkeypatch.setattr(api, "_director_messages", fake_director)
    first = await first_messages(budget, 1)
    assert first == [{"type": "event", "active": 1}]
    assert seen_reasons == [None]  # Granted: the live model client is used.
    assert (budget.active, budget.started_today) == (0, 1)
