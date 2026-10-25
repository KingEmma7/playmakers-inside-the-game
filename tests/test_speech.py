from __future__ import annotations

from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from replay_api import speech
from replay_api.main import app

RESOURCE = "/subscriptions/s/resourceGroups/g/providers/Microsoft.CognitiveServices/accounts/a"
HEADERS = {"X-Playmakers-Speech": "1"}


@pytest.fixture(autouse=True)
def isolated_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AZURE_SPEECH_KEY",
        "AZURE_SPEECH_REGION",
        "AZURE_SPEECH_RESOURCE_ID",
        "AZURE_SPEECH_ENDPOINT",
        "PLAYMAKERS_DAILY_SPEECH_CHARS",
    ):
        monkeypatch.delenv(name, raising=False)
    speech.cache.clear()
    monkeypatch.setattr(speech, "budget", speech.SpeechBudget())
    monkeypatch.setattr(speech, "limiter", speech.RateLimiter(1000, 1000))


def configure(monkeypatch: pytest.MonkeyPatch, endpoint: str = "") -> None:
    monkeypatch.setenv("AZURE_SPEECH_REGION", "westeurope")
    monkeypatch.setenv("AZURE_SPEECH_RESOURCE_ID", RESOURCE)
    monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", endpoint)


def test_speech_is_off_without_env_and_never_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_SPEECH_REGION", "AZURE_SPEECH_RESOURCE_ID", "AZURE_SPEECH_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(app)
    assert client.get("/speech/config").json() == {
        "azure": False,
        "region": None,
        "remaining_daily_chars": 60000,
    }
    response = client.get("/speech/synthesize", params={"text": "Goal"}, headers=HEADERS)
    assert response.status_code == 503
    assert client.get("/speech/synthesize", params={"text": "Goal"}).status_code == 400
    too_long = client.get("/speech/synthesize", params={"text": "x" * 281}, headers=HEADERS)
    assert too_long.status_code == 422


@pytest.mark.asyncio
async def test_azure_request_uses_entra_token_and_escaped_ssml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(monkeypatch, "https://playmakers.cognitiveservices.azure.com/")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"mp3")

    settings = speech.AzureSpeechSettings.from_env()
    assert settings is not None
    audio = await speech.synthesize(
        settings, "Gol <de> Okafor & co", "es", "tok", httpx.MockTransport(handler)
    )
    assert audio == b"mp3"
    request = seen[0]
    assert (
        str(request.url)
        == "https://playmakers.cognitiveservices.azure.com/tts/cognitiveservices/v1"
    )
    assert request.headers["Authorization"] == f"Bearer aad#{RESOURCE}#tok"
    assert "Ocp-Apim-Subscription-Key" not in request.headers
    body = request.content.decode()
    assert "es-ES-AlvaroNeural" in body
    assert "Gol &lt;de&gt; Okafor &amp; co" in body


def test_route_returns_audio_with_a_stubbed_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    captured: dict[str, str] = {}

    async def fake_synthesize(settings, text, language, token, **kwargs):
        captured.update(url=settings.synthesis_url, text=text, language=language, token=token)
        return b"mp3"

    monkeypatch.setattr(speech, "entra_token", lambda: "tok")
    monkeypatch.setattr(speech, "synthesize", fake_synthesize)
    client = TestClient(app)
    assert client.get("/speech/config").json() == {
        "azure": True,
        "region": "westeurope",
        "remaining_daily_chars": 60000,
    }
    response = client.get(
        "/speech/synthesize", params={"text": "Goal", "language": "fr"}, headers=HEADERS
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert captured == {
        "url": "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1",
        "text": "Goal",
        "language": "fr",
        "token": "tok",
    }


def test_post_unconfigured() -> None:
    response = TestClient(app).post(
        "/speech/tts", json={"text": "Goal", "language": "en", "emphasis": "goal"}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "unconfigured"}


def test_key_auth_cache_and_daily_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_SPEECH_KEY", "fake-test-key")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "westeurope")
    monkeypatch.setenv("PLAYMAKERS_DAILY_SPEECH_CHARS", "8")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"mp3")

    original = speech.synthesize

    async def stub(settings, text, language, token, **kwargs):
        return await original(
            settings, text, language, token, httpx.MockTransport(handler), **kwargs
        )

    monkeypatch.setattr(speech, "synthesize", stub)
    monkeypatch.setattr(
        speech, "entra_token", lambda: pytest.fail("Key auth must not request a token")
    )
    client = TestClient(app)
    for language, voice in [("en", "Ryan"), ("fr", "Henri")]:
        body = {"text": "But!", "language": language, "emphasis": "goal"}
        assert client.post("/speech/tts", json=body).content == b"mp3"
        assert client.post("/speech/tts", json=body).content == b"mp3"
        request = seen[-1]
        assert request.headers["Ocp-Apim-Subscription-Key"] == "fake-test-key"
        assert "Authorization" not in request.headers
        assert (
            str(request.url) == "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1"
        )
        assert f"{voice}Neural" in request.content.decode()
        assert "<prosody pitch='+12%' rate='+12%'" in request.content.decode()
    assert len(seen) == 2
    assert client.get("/speech/config").json()["remaining_daily_chars"] == 0
    assert "fake-test-key" not in client.get("/speech/config").text
    assert "fake-test-key" not in repr(speech.AzureSpeechSettings.from_env())
    response = client.post("/speech/tts", json={"text": "More"})
    assert response.status_code == 429
    assert "Daily speech character cap" in response.json()["detail"]
    assert len(seen) == 2
    # GET shares the POST cache and remains free after the cap is exhausted.
    assert (
        client.get(
            "/speech/synthesize",
            params={"text": "But!", "language": "en", "emphasis": "goal"},
            headers=HEADERS,
        ).status_code
        == 200
    )
    assert len(seen) == 2


def test_daily_budget_resets_at_utc_midnight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYMAKERS_DAILY_SPEECH_CHARS", "4")
    day = [date(2026, 10, 25)]
    budget = speech.SpeechBudget(today=lambda: day[0])
    assert budget.remaining(4) == 0
    with pytest.raises(speech.HTTPException):
        budget.remaining(1)
    day[0] = date(2026, 10, 26)
    assert budget.remaining(1) == 3


def test_lru_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    monkeypatch.setattr(speech, "entra_token", lambda: "tok")
    monkeypatch.setattr(speech, "CACHE_ENTRIES", 2)
    calls = []

    async def stub(settings, text, *args, **kwargs):
        calls.append(text)
        return b"mp3"

    monkeypatch.setattr(speech, "synthesize", stub)
    client = TestClient(app)
    for text in ["one", "two", "one", "three", "two"]:
        assert client.post("/speech/tts", json={"text": text}).status_code == 200
    assert calls == ["one", "two", "three", "two"]
    assert len(speech.cache) == 2
