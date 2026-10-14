from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from typing import Any

from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    Message,
    ResponseStream,
)


class DeterministicMockChatClient(BaseChatClient[Mapping[str, Any]]):
    """Credential-free client that answers the same typed insight prompt as live models."""

    def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> Awaitable[ChatResponse] | ResponseStream[ChatResponseUpdate, ChatResponse]:
        async def response() -> ChatResponse:
            await self._validate_options(options)
            data = json.loads(next(m.text for m in reversed(messages) if m.role == "user"))
            if data.get("task") == "what_if_explanation":
                observed = data["metrics"]["after"]["win"]
                counter = data["metrics"]["counterfactual"]["win"]
                relation = (
                    "higher"
                    if observed > counter
                    else "lower"
                    if observed < counter
                    else "unchanged"
                )
                return ChatResponse(
                    messages=[
                        Message(
                            "assistant",
                            [
                                f"The home side's win chance is {relation} in the observed state compared with the alternative: {data['scenario']}. "
                                "Seeded synthetic continuations estimate the difference."
                            ],
                        )
                    ],
                    model="gallery-mock",
                )
            event = data["event"]
            kind = data["kind"]
            text = json.dumps(
                {
                    "insight_id": f"{event['event_id']}:{kind}",
                    "clock_ms": event["clock_ms"],
                    "kind": kind,
                    "headline": "Passing under pressure"
                    if kind == "tactics"
                    else "The match develops",
                    "detail": "The passing pattern shapes the next attack."
                    if kind == "tactics"
                    else "Both fictional sides are building their match story.",
                    "metrics": data["metrics"],
                    "evidence_event_ids": data["evidence_event_ids"],
                }
            )
            return ChatResponse(messages=[Message("assistant", [text])], model="gallery-mock")

        if not stream:
            return response()

        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            result = await response()
            yield ChatResponseUpdate(
                contents=[Content.from_text(result.text)], role="assistant", model="gallery-mock"
            )

        return self._build_response_stream(updates())


def create_gallery_chat_client() -> BaseChatClient:
    """Live models are selected only by explicit Gallery environment configuration."""
    if endpoint := os.getenv("AZURE_AI_PROJECT_ENDPOINT"):
        from agent_framework_foundry import FoundryChatClient
        from azure.identity.aio import DefaultAzureCredential

        model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT")
        if not model:
            raise ValueError("AZURE_AI_MODEL_DEPLOYMENT is required with AZURE_AI_PROJECT_ENDPOINT")
        return FoundryChatClient(
            project_endpoint=endpoint, model=model, credential=DefaultAzureCredential()
        )
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if endpoint and deployment:
        from agent_framework_openai import OpenAIChatCompletionClient
        from azure.identity.aio import DefaultAzureCredential

        return OpenAIChatCompletionClient(
            azure_endpoint=endpoint, model=deployment, credential=DefaultAzureCredential()
        )
    return DeterministicMockChatClient()
