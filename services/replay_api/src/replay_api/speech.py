from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from threading import Lock
from typing import Literal
from xml.sax.saxutils import escape

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from replay_api.limits import RateLimiter, _env_int, client_key, utc_today

VOICES = {
    "en": ("en-GB", "en-GB-RyanNeural"),
    "es": ("es-ES", "es-ES-AlvaroNeural"),
    "fr": ("fr-FR", "fr-FR-HenriNeural"),
}
SCOPE = "https://cognitiveservices.azure.com/.default"
MAX_CHARS = 4000
Language = Literal["en", "es", "fr"]
Emphasis = Literal["normal", "goal", "big"]
router = APIRouter(prefix="/speech")
limiter = RateLimiter.for_speech()


@dataclass(frozen=True)
class AzureSpeechSettings:
    region: str
    resource_id: str
    endpoint: str
    key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> AzureSpeechSettings | None:
        region = os.getenv("AZURE_SPEECH_REGION", "").strip()
        resource_id = os.getenv("AZURE_SPEECH_RESOURCE_ID", "").strip()
        key = os.getenv("AZURE_SPEECH_KEY", "").strip()
        if not region or not (key or resource_id):
            return None
        endpoint = os.getenv("AZURE_SPEECH_ENDPOINT", "").strip().rstrip("/") or (
            f"https://{region}.tts.speech.microsoft.com"
        )
        if key:
            endpoint = f"https://{region}.tts.speech.microsoft.com"
        return cls(region=region, resource_id=resource_id, endpoint=endpoint, key=key)

    @property
    def synthesis_url(self) -> str:
        if self.endpoint.endswith(".cognitiveservices.azure.com"):
            return f"{self.endpoint}/tts/cognitiveservices/v1"
        return f"{self.endpoint}/cognitiveservices/v1"


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CHARS)
    language: Language = "en"
    emphasis: Emphasis = "normal"


class SpeechBudget:
    """Process-local UTC daily character budget; cache hits are free."""

    def __init__(self, today: Callable[[], date] = utc_today) -> None:
        self.today = today
        self.day = today()
        self.used = 0
        self.lock = Lock()

    def remaining(self, reserve: int = 0) -> int:
        with self.lock:
            if (day := self.today()) != self.day:
                self.day, self.used = day, 0
            cap = _env_int("PLAYMAKERS_DAILY_SPEECH_CHARS", 60000)
            if reserve > max(0, cap - self.used):
                raise HTTPException(
                    429, "Daily speech character cap reached; use browser commentary"
                )
            self.used += reserve
            return max(0, cap - self.used)


class AzureSpeechBucket:
    """Thread-safe process-wide token bucket for uncached Azure transactions."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.updated = clock()
        self.tokens = float(self.per_minute)
        self.lock = Lock()

    @property
    def per_minute(self) -> int:
        return _env_int("PLAYMAKERS_SPEECH_AZURE_PER_MINUTE", 18)

    def acquire(self) -> bool:
        with self.lock:
            now = self.clock()
            rate = self.per_minute
            self.tokens = min(float(rate), self.tokens + (now - self.updated) * rate / 60)
            self.updated = now
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True


azure_bucket = AzureSpeechBucket()

budget = SpeechBudget()
cache: OrderedDict[tuple[str, Emphasis, str], bytes] = OrderedDict()
cache_lock = Lock()
CACHE_ENTRIES = 256


def ssml(text: str, language: Language, emphasis: Emphasis = "normal") -> str:
    locale, voice = VOICES[language]
    pitch, rate, volume = {
        "normal": ("+0%", "+5%", "medium"),
        "big": ("+6%", "+8%", "loud"),
        "goal": ("+12%", "+12%", "loud"),
    }[emphasis]
    return (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{locale}'>"
        f"<voice xml:lang='{locale}' name='{voice}'>"
        f"<prosody pitch='{pitch}' rate='{rate}' volume='{volume}'>"
        f"{escape(text)}</prosody></voice></speak>"
    )


def entra_token() -> str:
    from azure.identity import DefaultAzureCredential
    from playmakers_agents.model_clients import credential_options

    return DefaultAzureCredential(**credential_options()).get_token(SCOPE).token


async def synthesize(
    settings: AzureSpeechSettings,
    text: str,
    language: Language,
    token: str = "",
    transport: httpx.AsyncBaseTransport | None = None,
    emphasis: Emphasis = "normal",
) -> bytes:
    auth = (
        {"Ocp-Apim-Subscription-Key": settings.key}
        if settings.key
        else {"Authorization": f"Bearer aad#{settings.resource_id}#{token}"}
    )
    async with httpx.AsyncClient(transport=transport, timeout=10) as client:
        response = await client.post(
            settings.synthesis_url,
            content=ssml(text, language, emphasis).encode("utf-8"),
            headers={
                **auth,
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
    return {
        "azure": settings is not None,
        "region": settings.region if settings else None,
        "remaining_daily_chars": budget.remaining(),
        "azure_per_minute": azure_bucket.per_minute,
    }


async def render_speech(request: Request, line: SpeechRequest) -> Response:
    if not limiter.allow(client_key(request)):
        raise HTTPException(status_code=429, detail="Too many speech requests; try again shortly")
    settings = AzureSpeechSettings.from_env()
    if settings is None:
        raise HTTPException(status_code=503, detail="unconfigured")
    key = (VOICES[line.language][1], line.emphasis, line.text)
    with cache_lock:
        audio = cache.get(key)
        if audio is not None:
            cache.move_to_end(key)
    if audio is None:
        try:
            if not azure_bucket.acquire():
                raise HTTPException(status_code=429, detail="busy")
            token = "" if settings.key else await asyncio.to_thread(entra_token)
            budget.remaining(reserve=len(line.text))
            audio = await synthesize(
                settings, line.text, line.language, token, emphasis=line.emphasis
            )
        except HTTPException:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise HTTPException(status_code=429, detail="busy") from exc
            raise HTTPException(status_code=502, detail="Azure AI Speech request failed") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Azure AI Speech request failed") from exc
        with cache_lock:
            cache[key] = audio
            cache.move_to_end(key)
            while len(cache) > CACHE_ENTRIES:
                cache.popitem(last=False)
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/tts")
async def speech_tts(request: Request, line: SpeechRequest) -> Response:
    return await render_speech(request, line)


@router.get("/synthesize")
async def speech_synthesize(
    request: Request,
    text: str = Query(min_length=1, max_length=280),
    language: Language = "en",
    emphasis: Emphasis = "normal",
    x_playmakers_speech: str | None = Header(default=None),
) -> Response:
    if x_playmakers_speech != "1":
        raise HTTPException(status_code=400, detail="Missing X-Playmakers-Speech header")
    return await render_speech(
        request, SpeechRequest(text=text, language=language, emphasis=emphasis)
    )
