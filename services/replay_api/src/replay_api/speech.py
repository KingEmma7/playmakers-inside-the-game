from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Literal
from xml.sax.saxutils import escape

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import Response

from replay_api.limits import RateLimiter, client_key

VOICES = {
    "en": ("en-GB", "en-GB-SoniaNeural"),
    "es": ("es-ES", "es-ES-ElviraNeural"),
    "fr": ("fr-FR", "fr-FR-DeniseNeural"),
}
SCOPE = "https://cognitiveservices.azure.com/.default"
MAX_CHARS = 280

router = APIRouter(prefix="/speech")
limiter = RateLimiter.for_speech()


@dataclass(frozen=True)
class AzureSpeechSettings:
    region: str
    resource_id: str
    endpoint: str

    @classmethod
    def from_env(cls) -> AzureSpeechSettings | None:
        region = os.getenv("AZURE_SPEECH_REGION", "").strip()
        resource_id = os.getenv("AZURE_SPEECH_RESOURCE_ID", "").strip()
        if not region or not resource_id:
            return None
        endpoint = os.getenv("AZURE_SPEECH_ENDPOINT", "").strip().rstrip("/") or (
            f"https://{region}.tts.speech.microsoft.com"
        )
        return cls(region=region, resource_id=resource_id, endpoint=endpoint)

    @property
    def synthesis_url(self) -> str:
        if self.endpoint.endswith(".cognitiveservices.azure.com"):
            return f"{self.endpoint}/tts/cognitiveservices/v1"
        return f"{self.endpoint}/cognitiveservices/v1"


def ssml(text: str, language: Literal["en", "es", "fr"]) -> str:
    locale, voice = VOICES[language]
    return (
        f"<speak version='1.0' xml:lang='{locale}'>"
        f"<voice xml:lang='{locale}' name='{voice}'>{escape(text)}</voice></speak>"
    )


def entra_token() -> str:
    from azure.identity import DefaultAzureCredential
    from playmakers_agents.model_clients import credential_options

    return DefaultAzureCredential(**credential_options()).get_token(SCOPE).token


async def synthesize(
    settings: AzureSpeechSettings,
    text: str,
    language: Literal["en", "es", "fr"],
    token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    async with httpx.AsyncClient(transport=transport, timeout=10) as client:
        response = await client.post(
            settings.synthesis_url,
            content=ssml(text, language).encode("utf-8"),
            headers={
                "Authorization": f"Bearer aad#{settings.resource_id}#{token}",
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                "User-Agent": "playmakers",
            },
        )
        response.raise_for_status()
        return response.content


@router.get("/config")
def speech_config() -> dict[str, object]:
    settings = AzureSpeechSettings.from_env()
    return {"azure": settings is not None, "region": settings.region if settings else None}


@router.get("/synthesize")
async def speech_synthesize(
    request: Request,
    text: str = Query(min_length=1, max_length=MAX_CHARS),
    language: Literal["en", "es", "fr"] = "en",
    x_playmakers_speech: str | None = Header(default=None),
) -> Response:
    if x_playmakers_speech != "1":
        raise HTTPException(status_code=400, detail="Missing X-Playmakers-Speech header")
    if not limiter.allow(client_key(request)):
        raise HTTPException(status_code=429, detail="Too many speech requests; try again shortly")
    settings = AzureSpeechSettings.from_env()
    if settings is None:
        raise HTTPException(status_code=503, detail="Azure AI Speech is not configured")
    try:
        token = await asyncio.to_thread(entra_token)
        audio = await synthesize(settings, text, language, token)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Azure AI Speech request failed") from exc
    return Response(content=audio, media_type="audio/mpeg")
