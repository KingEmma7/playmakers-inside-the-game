from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any, Literal

from agent_framework import Agent, BaseChatClient
from playmakers_schema.models import GoalEvent, MatchEvent
from pydantic import BaseModel

from playmakers_agents.contracts import OverlayCue, ViewerProfile
from playmakers_agents.model_clients import DeterministicMockChatClient
from playmakers_agents.players import player_name
from playmakers_agents.recap import team_name


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


GOAL_PHRASES = {
    "en": (
        ("{player} scores for {team}!", "What a finish. The crowd is on its feet."),
        ("Goal! {player} puts it away for {team}.", "Cool as you like in front of goal."),
        ("{team} celebrate: {player} finds the net!", "That one changes the mood of the match."),
    ),
    "es": (
        ("¡Gol de {player} para {team}!", "Qué definición. La grada se pone en pie."),
        ("¡{player} marca para {team}!", "Frialdad total delante de la portería."),
        ("¡{team} lo celebra: gol de {player}!", "Este gol cambia el ánimo del partido."),
    ),
    "fr": (
        ("But de {player} pour {team} !", "Quelle finition. Le public est debout."),
        ("{player} marque pour {team} !", "Un sang-froid parfait devant le but."),
        ("{team} exulte : but de {player} !", "Ce but change l'ambiance du match."),
    ),
}
TEAM_ONLY = {"en": "a {team} player", "es": "un jugador de {team}", "fr": "un joueur de {team}"}


def goal_phrase(event: GoalEvent, language: Literal["en", "es", "fr"]) -> tuple[str, str]:
    variants = GOAL_PHRASES[language]
    digest = hashlib.sha256(event.event_id.encode()).digest()
    headline, detail = variants[digest[0] % len(variants)]
    team = team_name(event.scoring_team_id)
    player = player_name(event.scorer_player_id) or TEAM_ONLY[language].format(team=team)
    return headline.format(player=player, team=team), detail


async def personalize(
    cue: OverlayCue,
    profile: ViewerProfile,
    event: MatchEvent,
    client: BaseChatClient,
    index: int,
    timeout: float = 1.5,
) -> OverlayCue:
    payload: dict[str, Any] = dict(cue.payload)
    headline, detail, team_label, player_label = PHRASES[profile.language]
    if profile.persona == "casual":
        if isinstance(event, GoalEvent) and cue.template != "what_if":
            headline, detail = goal_phrase(event, profile.language)
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
    # Fan lines and rule-written captions are already localized; only model prose is translated.
    model_written = cue.provenance is None or cue.provenance.source == "agent"
    if (
        profile.language != "en"
        and profile.persona == "analyst"
        and model_written
        and not isinstance(client, DeterministicMockChatClient)
    ):
        try:
            response = await asyncio.wait_for(
                Agent(
                    client,
                    name="audience_translation",
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
                timeout=timeout,
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
            "provenance": cue.provenance
            and cue.provenance.model_copy(update={"personalized_for": profile.persona}),
            "language": profile.language,
            "payload": payload,
        }
    )
