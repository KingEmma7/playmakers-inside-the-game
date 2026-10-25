from __future__ import annotations

import asyncio
import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from replay_api import ask
from replay_api.limits import AskBudget, RateLimiter
from replay_api.main import app


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ask, "live_model_configured", lambda: False)
    monkeypatch.setattr(ask, "budget", AskBudget(60))
    monkeypatch.setattr(ask, "limiter", RateLimiter(1000, 1000))


@pytest.fixture(scope="module")
def events():
    return simulate_match(MatchConfig(seed=382))


def post(events, question="shots", language="en", upto=None):
    return TestClient(app).post(
        "/ask",
        json={
            "seed": 382,
            "upto_event_id": upto or events[100].event_id,
            "question": question,
            "language": language,
        },
    )


def stub(monkeypatch, result, seen=None):
    class Client:
        async def get_response(self, messages):
            if seen is not None:
                seen.extend(m.text for m in messages)
            if isinstance(result, Exception):
                raise result
            return SimpleNamespace(text=json.dumps(result) if isinstance(result, dict) else result)

    monkeypatch.setattr(ask, "live_model_configured", lambda: True)
    monkeypatch.setattr(ask, "create_playmakers_chat_client", Client)


def test_model_filters_ids_and_never_sees_future(monkeypatch, events):
    seen = []
    stub(
        monkeypatch,
        {
            "answer": "A shot was recorded.",
            "cited_event_ids": [events[32].event_id, "fake", events[101].event_id],
            "answerable": True,
        },
        seen,
    )
    data = post(events).json()
    assert data["source"] == "model"
    assert data["cited_event_ids"] == [events[32].event_id]
    assert events[101].event_id not in " ".join(seen)
    assert all(
        i in {e.event_id for e in events[:101]}
        for f in ask.evidence(events[:101], "shots")
        for i in f.ids
    )


@pytest.mark.parametrize(
    "question",
    ["who will win the Premier League?", "give me a betting tip", "predict tomorrow's score"],
)
@pytest.mark.parametrize("language", ["en", "es", "fr"])
def test_off_match_never_calls_model(monkeypatch, events, question, language):
    monkeypatch.setattr(
        ask, "live_model_configured", lambda: pytest.fail("Must refuse before model")
    )
    data = post(events, question, language).json()
    assert data["answerable"] is False
    assert data["cited_event_ids"] == []
    assert data["answer"] == ask.REFUSAL[language]


@pytest.mark.parametrize(
    "result",
    [
        RuntimeError("down"),
        TimeoutError(),
        "invalid json",
        {"answer": "There were 9999 shots.", "cited_event_ids": ["fake"], "answerable": True},
    ],
)
def test_model_failure_or_invalid_output_falls_back(monkeypatch, events, result):
    stub(monkeypatch, result)
    data = post(events).json()
    assert data["source"] == "rules" and data["answerable"]
    assert data["cited_event_ids"]


def test_numbers_checked_without_event_id_digits(monkeypatch, events):
    stub(
        monkeypatch,
        {
            "answer": "There were 382 shots.",
            "cited_event_ids": [events[32].event_id],
            "answerable": True,
        },
    )
    assert post(events).json()["source"] == "rules"


def test_cap_uses_rules_with_note(monkeypatch, events):
    monkeypatch.setattr(ask, "live_model_configured", lambda: True)
    monkeypatch.setattr(ask, "budget", AskBudget(0))
    data = post(events).json()
    assert data["source"] == "rules" and data["note"]


def test_unknown_cutoff_and_rate_limit(monkeypatch, events):
    assert post(events, upto="missing").status_code == 404
    monkeypatch.setattr(ask, "limiter", RateLimiter(1, 100))
    assert post(events).status_code == 200
    assert post(events).status_code == 429


@pytest.mark.parametrize(
    "question",
    [
        "why did Marin score?",
        "who is pressing best?",
        "shots and xG?",
        "cards?",
        "possession?",
        "Marin involvement?",
    ],
)
def test_offline_intents(events, question):
    data = post(events, question, upto=events[-1].event_id).json()
    assert data["source"] == "rules" and data["answerable"]
    assert set(data["cited_event_ids"]) <= {e.event_id for e in events}


def test_daily_reset_and_env(monkeypatch):
    day = date(2026, 10, 25)
    budget = AskBudget(1, lambda: day)
    assert budget.acquire()
    assert not budget.acquire()
    day = date(2026, 10, 26)
    assert budget.acquire()
    monkeypatch.setenv("PLAYMAKERS_DAILY_ASK_MODEL_CALLS", "4")
    assert AskBudget.from_env().daily == 4


def test_invalid_bounds(events):
    client = TestClient(app)
    for changes in (
        {"seed": -1},
        {"seed": 10001},
        {"question": " "},
        {"question": "x" * 201},
        {"language": "de"},
    ):
        body = {
            "seed": 382,
            "upto_event_id": events[100].event_id,
            "question": "shots",
            "language": "en",
        } | changes
        assert client.post("/ask", json=body).status_code == 422


def test_model_deadline(monkeypatch, events):
    original = asyncio.timeout
    monkeypatch.setattr(ask.asyncio, "timeout", lambda _: original(0.01))

    class Slow:
        async def get_response(self, messages):
            await asyncio.sleep(1)

    monkeypatch.setattr(ask, "live_model_configured", lambda: True)
    monkeypatch.setattr(ask, "create_playmakers_chat_client", Slow)
    assert post(events).json()["source"] == "rules"


def test_cors_post_keeps_origin_allowlist():
    client = TestClient(app)
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    assert client.options("/ask", headers=headers).status_code == 200
    headers["Origin"] = "https://untrusted.invalid"
    assert client.options("/ask", headers=headers).status_code == 400


def test_unassisted_seed_goal_includes_minute_without_invented_pass(events):
    goal = next(e for e in events if e.event_type == "goal")
    data = post(events, "why did Marin score?", upto=goal.event_id).json()
    assert "Marin scored with a right foot shot (xG 0.30) in the 2nd minute." == data["answer"]
    assert set(data["cited_event_ids"]) == {goal.event_id, goal.shot_event_id}


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (
            "en",
            "Okafor's pass found Marin, who scored with a right foot shot (xG 0.30) in the 2nd minute.",
        ),
        (
            "fr",
            "La passe de Okafor a trouvé Marin, qui a marqué sur une frappe du pied droit (xG 0.30) à la 2e minute.",
        ),
        (
            "es",
            "El pase de Okafor encontró a Marin, que marcó con un remate de pie derecho (xG 0.30) en el minuto 2.",
        ),
    ],
)
def test_goal_rules_link_preceding_completed_pass(events, language, expected):
    goal_index = next(i for i, e in enumerate(events) if e.event_type == "goal")
    prefix = list(events[: goal_index + 1])
    goal = prefix[-1]
    carry = prefix[-3]
    template = next(e for e in events if e.event_type == "pass")
    assist = template.model_copy(
        update={
            "event_id": carry.event_id,
            "sequence": carry.sequence,
            "clock_ms": carry.clock_ms,
            "team_id": goal.scoring_team_id,
            "from_player_id": "match_382_H09",
            "to_player_id": goal.scorer_player_id,
            "completed": True,
        }
    )
    prefix[-3] = assist
    answer = ask.rules("why did Marin score?", ask.evidence(prefix, "Marin"), language)
    assert answer.answer == expected
    assert set(answer.cited_event_ids) == {assist.event_id, goal.shot_event_id, goal.event_id}
    # An incomplete or opposition pass, stale pass, or different recipient is no assist.
    for changes in (
        {"completed": False},
        {"team_id": "match_382_AWAY"},
        {"to_player_id": "match_382_H08"},
        {"clock_ms": 1},
    ):
        prefix[-3] = assist.model_copy(update=changes)
        answer = ask.rules("why did Marin score?", ask.evidence(prefix, "Marin"), language)
        assert assist.event_id not in answer.cited_event_ids
