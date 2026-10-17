from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from agent_framework import Agent, BaseChatClient
from playmakers_schema.models import MatchEvent
from pydantic import BaseModel

from playmakers_agents.contracts import OverlayCue, ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient


class Caption(BaseModel):
    headline: str
    detail: str


PHRASES = {
    "en": (
        "Here comes the next attack!",
        "Follow the action as the match unfolds.",
        "Favourite",
        "Favourite",
    ),
    "es": (
        "¡Llega el próximo ataque!",
        "Sigue la emoción del partido.",
        "Favorito",
        "Favorito",
    ),
    "fr": (
        "Voici la prochaine attaque !",
        "Suivez les émotions du match.",
        "Favori",
        "Favori",
    ),
}


async def personalize(
    cue: OverlayCue, profile: ViewerProfile, event: MatchEvent, client: BaseChatClient, index: int
) -> OverlayCue:
    payload: dict[str, Any] = dict(cue.payload)
    headline, detail, team_label, player_label = PHRASES[profile.language]
    if profile.persona == "casual":
        payload.update(headline=headline, detail=detail, metrics={})
        if cue.template == "what_if":
            payload["detail"] = {
                "en": "Imagine how a different outcome could change the match.",
                "es": "Imagina cómo otro resultado podría cambiar el partido.",
                "fr": "Imaginez comment une autre issue pourrait changer le match.",
            }[profile.language]
            payload["metrics"] = {
                key: value
                for key, value in cue.payload["metrics"].items()
                if key
                in (
                    "win_prob_before",
                    "win_prob_after",
                    "win_prob_counterfactual",
                    "delta",
                    "rollouts",
                )
            }
        payload["tone"] = "fan"
    else:
        payload["tactical_label"] = "pressure_and_control"
        if profile.language != "en":
            payload["headline"] = {"es": "Análisis del partido", "fr": "Analyse du match"}[
                profile.language
            ]
            payload["detail"] = {
                "es": "Presión y control: métricas verificadas.",
                "fr": "Pression et contrôle : mesures vérifiées.",
            }[profile.language]
    if profile.language != "en" and not isinstance(client, DeterministicMockChatClient):
        try:
            response = await asyncio.wait_for(
                Agent(
                    client,
                    instructions="Translate the supplied caption to the requested language. Return JSON with headline and detail. "
                    "Preserve meaning and numbers exactly.",
                ).run(
                    json.dumps(
                        {
                            "language": profile.language,
                            "headline": cue.payload["headline"]
                            if profile.persona == "analyst"
                            else payload["headline"],
                            "detail": cue.payload["detail"]
                            if profile.persona == "analyst"
                            else payload["detail"],
                        }
                    )
                ),
                timeout=1.5,
            )
            caption = Caption.model_validate_json(response.text)
            source = cue.payload if profile.persona == "analyst" else payload
            original_numbers = sorted(
                re.findall(r"\d+(?:\.\d+)?", source["headline"] + " " + source["detail"])
            )
            translated_numbers = sorted(
                re.findall(r"\d+(?:\.\d+)?", caption.headline + " " + caption.detail)
            )
            if original_numbers != translated_numbers:
                raise ValueError("Translation changed verified numbers")
            payload.update(caption.model_dump())
        except Exception:
            pass  # Small offline phrase table also covers unavailable translation models.
    if profile.favorite_team_id and profile.favorite_team_id == (
        getattr(event, "scoring_team_id", None) or event.team_id
    ):
        payload["headline"] = f"{team_label}: {payload['headline']}"
        payload["favorite_team_id"] = profile.favorite_team_id
    involved = {
        getattr(event, name, None)
        for name in (
            "player_id",
            "from_player_id",
            "to_player_id",
            "passer_player_id",
            "receiver_player_id",
            "shooter_player_id",
            "scorer_player_id",
            "carrier_player_id",
            "carded_player_id",
            "assist_player_id",
        )
    }
    if profile.favorite_player_id and profile.favorite_player_id in involved:
        payload["headline"] = f"{player_label}: {payload['headline']}"
        payload["player_cam"] = {"player_id": profile.favorite_player_id}
    return cue.model_copy(
        update={
            "cue_id": f"{cue.cue_id}:viewer{index}",
            "persona": profile.persona,
            "language": profile.language,
            "payload": payload,
        }
    )
