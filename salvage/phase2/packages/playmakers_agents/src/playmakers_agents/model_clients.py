from __future__ import annotations

import os
import re
from typing import Any, Mapping

from openai import AsyncAzureOpenAI, AsyncOpenAI

from agent_framework import BaseChatClient, ChatResponse, Message


class DeterministicMockChatClient(BaseChatClient[Mapping[str, Any]]):
    """
    Credential-free chat client for offline runs and CI.

    This intentionally does NOT attempt tool-calling. LLM-backed agents should
    be written so they can fall back to deterministic heuristics when this
    mock is selected.
    """

    def __init__(self, *, model: str = "mock") -> None:
        super().__init__()
        self._model = model

    async def _inner_get_response(
        self,
        *,
        messages: list[Message] | tuple[Message, ...],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ):
        _ = (stream, options, kwargs)
        prompt = "\n".join(str(c) for m in messages for c in m.contents)

        # Very small deterministic behavior: echo a "structured-ish" summary.
        headline = "Mock insight"
        if re.search(r"goal", prompt, flags=re.IGNORECASE):
            headline = "Key moment"
        text = f"{headline}: offline deterministic mock response"

        return ChatResponse(messages=Message("assistant", [text]), model=self._model)


class AzureOpenAIChatClient(BaseChatClient[Mapping[str, Any]]):
    def __init__(self, *, endpoint: str, api_key: str, deployment: str, api_version: str) -> None:
        super().__init__()
        self._client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        self._deployment = deployment

    async def _inner_get_response(
        self,
        *,
        messages: list[Message] | tuple[Message, ...],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ):
        _ = (stream, options, kwargs)
        payload = []
        for m in messages:
            payload.append({"role": m.role, "content": "\n".join(str(c) for c in m.contents)})
        resp = await self._client.chat.completions.create(model=self._deployment, messages=payload)
        text = resp.choices[0].message.content or ""
        return ChatResponse(messages=Message("assistant", [text]), model=str(self._deployment))


class FoundryOpenAICompatChatClient(BaseChatClient[Mapping[str, Any]]):
    """
    Foundry-hosted models often expose an OpenAI-compatible chat endpoint.
    """

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        super().__init__()
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def _inner_get_response(
        self,
        *,
        messages: list[Message] | tuple[Message, ...],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ):
        _ = (stream, options, kwargs)
        payload = []
        for m in messages:
            payload.append({"role": m.role, "content": "\n".join(str(c) for c in m.contents)})
        resp = await self._client.chat.completions.create(model=self._model, messages=payload)
        text = resp.choices[0].message.content or ""
        return ChatResponse(messages=Message("assistant", [text]), model=self._model)


def create_playmakers_chat_client() -> BaseChatClient:
    """
    Pluggable model client selection.

    - If Foundry / Azure OpenAI env vars are not present, returns a deterministic mock.
    - If env vars are present but required optional deps are missing, raises at runtime.

    Env conventions (Phase 2):
    - Foundry (OpenAI-compatible): `FOUNDRY_ENDPOINT`, `FOUNDRY_API_KEY`, `FOUNDRY_MODEL`
    - Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`
    """
    foundry_endpoint = os.getenv("FOUNDRY_ENDPOINT")
    foundry_api_key = os.getenv("FOUNDRY_API_KEY")
    foundry_model = os.getenv("FOUNDRY_MODEL")
    if foundry_endpoint and foundry_api_key and foundry_model:
        return FoundryOpenAICompatChatClient(
            base_url=foundry_endpoint.rstrip("/"),
            api_key=foundry_api_key,
            model=foundry_model,
        )

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    if azure_endpoint and azure_key and azure_deployment:
        return AzureOpenAIChatClient(
            endpoint=azure_endpoint.rstrip("/"),
            api_key=azure_key,
            deployment=azure_deployment,
            api_version=azure_api_version,
        )

    return DeterministicMockChatClient()
