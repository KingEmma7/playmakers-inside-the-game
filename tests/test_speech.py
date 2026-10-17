from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from replay_api import speech
from replay_api.main import app

RESOURCE = "/subscriptions/s/resourceGroups/g/providers/Microsoft.CognitiveServices/accounts/a"
HEADERS = {"X-Playmakers-Speech": "1"}


def configure(monkeypatch: pytest.MonkeyPatch, endpoint: str = "") -> None:
    monkeypatch.setenv("AZURE_SPEECH_REGION", "westeurope")
    monkeypatch.setenv("AZURE_SPEECH_RESOURCE_ID", RESOURCE)
    monkeypatch.setenv("AZURE_SPEECH_ENDPOINT", endpoint)


def test_speech_is_off_without_env_and_never_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_SPEECH_REGION", "AZURE_SPEECH_RESOURCE_ID", "AZURE_SPEECH_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    client = TestClient(app)
    assert client.get("/speech/config").json() == {"azure": False, "region": None}
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
    assert "es-ES-ElviraNeural" in body
    assert "Gol &lt;de&gt; Okafor &amp; co" in body


def test_route_returns_audio_with_a_stubbed_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)
    captured: dict[str, str] = {}

    async def fake_synthesize(settings, text, language, token):
        captured.update(url=settings.synthesis_url, text=text, language=language, token=token)
        return b"mp3"

    monkeypatch.setattr(speech, "entra_token", lambda: "tok")
    monkeypatch.setattr(speech, "synthesize", fake_synthesize)
    client = TestClient(app)
    assert client.get("/speech/config").json() == {"azure": True, "region": "westeurope"}
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
