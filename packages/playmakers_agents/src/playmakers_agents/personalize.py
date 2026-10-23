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


# All variants describe only fields present on the cited event. Selection is stable
# across processes; the audience executor avoids repeating the previous visible line.
FAN_LINES = {
    "en": {
        "pass": (
            "{player} plays it to {receiver}.",
            "{receiver} receives from {player}.",
            "The ball goes from {player} to {receiver}.",
        ),
        "incomplete": (
            "{player}'s pass does not reach {receiver}.",
            "{player} cannot find {receiver}.",
            "No completed pass from {player} to {receiver}.",
        ),
        "pressure": (
            "{player} passes under pressure.",
            "Pressure on {player} as the ball moves on.",
            "{player} has company on the ball.",
        ),
        "carry": (
            "{player} carries the ball.",
            "{player} moves with the ball.",
            "The ball stays with {player}.",
        ),
        "shot": (
            "Chance! {player} takes a shot.",
            "{player} goes for goal.",
            "A shot from {player}!",
        ),
        "saved": (
            "Saved! {player}'s shot is stopped.",
            "{player} shoots, but the keeper saves.",
            "The keeper denies {player}.",
        ),
        "foul": (
            "{player} commits a foul.",
            "A foul by {player} stops play.",
            "Play stops after {player}'s foul.",
        ),
        "card": (
            "{player} is shown {color}.",
            "{color} for {player}.",
            "The referee shows {player} {color}.",
        ),
        "possession_change": (
            "{team} take possession.",
            "The ball is now with {team}.",
            "Possession goes to {team}.",
        ),
        "tackle": (
            "{player} makes a tackle.",
            "A tackle from {player}.",
            "{player} challenges for the ball.",
        ),
        "substitution": (
            "{player} comes on for {receiver}.",
            "{receiver} makes way for {player}.",
            "A change: {player} replaces {receiver}.",
        ),
        "kickoff": ("{team} kick off.", "Kickoff for {team}.", "{team} start from the centre."),
        "period_start": (
            "The half begins.",
            "A new half starts.",
            "The match clock starts for this half.",
        ),
        "period_end": ("The half ends.", "The whistle ends the half.", "Play ends for this half."),
        "tracking_frame": (
            "Player positions updated.",
            "The pitch positions refresh.",
            "A new view of the player positions.",
        ),
    },
    "es": {
        "pass": (
            "{player} pasa a {receiver}.",
            "{receiver} recibe de {player}.",
            "El balón va de {player} a {receiver}.",
        ),
        "incomplete": (
            "El pase de {player} no llega a {receiver}.",
            "{player} no encuentra a {receiver}.",
            "Pase incompleto de {player} hacia {receiver}.",
        ),
        "pressure": (
            "{player} pasa bajo presión.",
            "Presión sobre {player} al pasar.",
            "{player} tiene compañía con el balón.",
        ),
        "carry": (
            "{player} conduce el balón.",
            "{player} avanza con el balón.",
            "El balón sigue con {player}.",
        ),
        "shot": ("¡Ocasión! {player} dispara.", "{player} busca el gol.", "¡Disparo de {player}!"),
        "saved": (
            "¡Parada! Detienen el disparo de {player}.",
            "{player} dispara, pero el portero para.",
            "El portero frena a {player}.",
        ),
        "foul": (
            "{player} comete una falta.",
            "Una falta de {player} detiene el juego.",
            "El juego se para por una falta de {player}.",
        ),
        "card": (
            "{player} recibe {color}.",
            "{color} para {player}.",
            "El árbitro muestra {color} a {player}.",
        ),
        "possession_change": (
            "{team} toma la posesión.",
            "El balón está con {team}.",
            "La posesión pasa a {team}.",
        ),
        "tackle": (
            "{player} hace una entrada.",
            "Entrada de {player}.",
            "{player} disputa el balón.",
        ),
        "substitution": (
            "{player} entra por {receiver}.",
            "{receiver} deja su sitio a {player}.",
            "Cambio: {player} sustituye a {receiver}.",
        ),
        "kickoff": (
            "{team} saca del centro.",
            "Saque inicial de {team}.",
            "{team} empieza desde el centro.",
        ),
        "period_start": (
            "Empieza la mitad.",
            "Comienza una nueva mitad.",
            "Arranca el reloj de esta mitad.",
        ),
        "period_end": (
            "Termina la mitad.",
            "El silbato cierra la mitad.",
            "Acaba el juego de esta mitad.",
        ),
        "tracking_frame": (
            "Posiciones actualizadas.",
            "Se actualizan las posiciones del campo.",
            "Nueva vista de las posiciones.",
        ),
    },
    "fr": {
        "pass": (
            "{player} passe à {receiver}.",
            "{receiver} reçoit de {player}.",
            "Le ballon va de {player} à {receiver}.",
        ),
        "incomplete": (
            "La passe de {player} n'atteint pas {receiver}.",
            "{player} ne trouve pas {receiver}.",
            "Passe manquée de {player} vers {receiver}.",
        ),
        "pressure": (
            "{player} passe sous pression.",
            "Pression sur {player} au moment de passer.",
            "{player} est accompagné sur le ballon.",
        ),
        "carry": (
            "{player} conduit le ballon.",
            "{player} avance avec le ballon.",
            "Le ballon reste avec {player}.",
        ),
        "shot": (
            "Occasion ! {player} frappe.",
            "{player} tente sa chance.",
            "Une frappe de {player} !",
        ),
        "saved": (
            "Arrêt ! Le tir de {player} est repoussé.",
            "{player} frappe, mais le gardien arrête.",
            "Le gardien fait obstacle à {player}.",
        ),
        "foul": (
            "{player} commet une faute.",
            "Une faute de {player} arrête le jeu.",
            "Le jeu s'arrête après la faute de {player}.",
        ),
        "card": (
            "{player} reçoit {color}.",
            "{color} pour {player}.",
            "L'arbitre montre {color} à {player}.",
        ),
        "possession_change": (
            "{team} prend possession du ballon.",
            "Le ballon est avec {team}.",
            "La possession passe à {team}.",
        ),
        "tackle": (
            "{player} effectue un tacle.",
            "Un tacle de {player}.",
            "{player} dispute le ballon.",
        ),
        "substitution": (
            "{player} entre pour {receiver}.",
            "{receiver} cède sa place à {player}.",
            "Changement : {player} remplace {receiver}.",
        ),
        "kickoff": (
            "{team} donne le coup d'envoi.",
            "Coup d'envoi pour {team}.",
            "{team} part du centre.",
        ),
        "period_start": (
            "La mi-temps commence.",
            "Une nouvelle mi-temps débute.",
            "Le chrono démarre pour cette mi-temps.",
        ),
        "period_end": (
            "La mi-temps se termine.",
            "Le sifflet termine la mi-temps.",
            "Fin du jeu pour cette mi-temps.",
        ),
        "tracking_frame": (
            "Positions actualisées.",
            "Les positions sur le terrain sont actualisées.",
            "Nouvelle vue des positions.",
        ),
    },
}


def is_significant(event: MatchEvent) -> bool:
    return event.event_type == "goal" or (event.event_type == "card" and event.color == "red")


def significant_phrase(
    event: MatchEvent, language: Literal["en", "es", "fr"], home: int, away: int
) -> tuple[str, str] | None:
    minute = event.clock_ms // 60_000 + 1
    if isinstance(event, GoalEvent):
        label = {"en": "GOAL", "es": "GOL", "fr": "BUT"}[language]
        headline = f"{label}, {player_name(event.scorer_player_id)} {minute}'"
        if home == away:
            detail = {
                "en": f"The score is level at {home}-{away}.",
                "es": f"Empate a {home}-{away}.",
                "fr": f"Égalité à {home}-{away}.",
            }[language]
        else:
            leader = team_name(event.match_id + ("_HOME" if home > away else "_AWAY"))
            scoreline = f"{max(home, away)}-{min(home, away)}"
            detail = {
                "en": f"{leader} lead {scoreline}.",
                "es": f"{leader} gana {scoreline}.",
                "fr": f"{leader} mène {scoreline}.",
            }[language]
        return headline, detail
    if event.event_type == "card" and event.color == "red":
        label = {"en": "RED CARD", "es": "TARJETA ROJA", "fr": "CARTON ROUGE"}[language]
        player = player_name(event.carded_player_id)
        return f"{label}, {player} {minute}'", {
            "en": f"{player} is sent off.",
            "es": f"{player} es expulsado.",
            "fr": f"{player} est expulsé.",
        }[language]
    return None


def fan_phrase(
    event: MatchEvent, language: Literal["en", "es", "fr"], previous: str = ""
) -> tuple[str, str]:
    data = event.model_dump()
    key = event.event_type
    if key == "pass":
        key = (
            "incomplete"
            if not data["completed"]
            else "pressure"
            if data["pressure"] >= 0.65
            else key
        )
    if key == "shot" and data["outcome"] == "saved":
        key = "saved"
    actor = next(
        (
            data[k]
            for k in (
                "shooter_player_id",
                "fouler_player_id",
                "carded_player_id",
                "tackler_player_id",
                "from_player_id",
                "player_in_id",
                "player_id",
            )
            if data.get(k)
        ),
        None,
    )
    values = {
        "player": player_name(actor)
        or {"en": "A player", "es": "Un jugador", "fr": "Un joueur"}[language],
        "receiver": player_name(data.get("to_player_id") or data.get("player_out_id"))
        or {"en": "a teammate", "es": "un compañero", "fr": "un coéquipier"}[language],
        "team": team_name(data.get("to_team_id") or event.team_id)
        if data.get("to_team_id") or event.team_id
        else {"en": "The team", "es": "El equipo", "fr": "L'équipe"}[language],
        "color": {
            "en": {"red": "a red card", "yellow": "a yellow card"},
            "es": {"red": "tarjeta roja", "yellow": "tarjeta amarilla"},
            "fr": {"red": "un carton rouge", "yellow": "un carton jaune"},
        }[language].get(data.get("color", ""), ""),
    }
    variants = FAN_LINES[language][key]
    offset = hashlib.sha256(event.event_id.encode()).digest()[0] % len(variants)
    for step in range(len(variants)):
        headline = variants[(offset + step) % len(variants)].format(**values)
        if headline != previous.removeprefix(
            {"en": "Favourite: ", "es": "Favorito: ", "fr": "Favori: "}[language]
        ).removeprefix({"en": "Favourite: ", "es": "Favorito: ", "fr": "Favori: "}[language]):
            break
    return headline, ""


async def personalize(
    cue: OverlayCue,
    profile: ViewerProfile,
    event: MatchEvent,
    client: BaseChatClient,
    index: int,
    timeout: float = 1.5,
    previous: str = "",
) -> OverlayCue:
    payload: dict[str, Any] = dict(cue.payload)
    team_label = player_label = {"en": "Favourite", "es": "Favorito", "fr": "Favori"}[
        profile.language
    ]
    significant = payload.get("moment") in ("goal", "card")
    if profile.persona == "casual":
        if cue.template != "what_if" and not significant:
            headline, detail = fan_phrase(event, profile.language, previous)
            payload.update(headline=headline, detail=detail, metrics={})
        elif cue.template == "what_if":
            payload["headline"] = {"en": "What if?", "es": "¿Y si?", "fr": "Et si ?"}[
                profile.language
            ]
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
    if significant:
        payload["headline"], payload["detail"] = significant_phrase(
            event,
            profile.language,
            int(cue.payload["metrics"].get("home_goals", 0)),
            int(cue.payload["metrics"].get("away_goals", 0)),
        )
    # Fan lines and rule-written captions are already localized; only model prose is translated.
    model_written = cue.provenance is None or cue.provenance.source == "agent"
    if (
        profile.language != "en"
        and profile.persona == "analyst"
        and model_written
        and not significant
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
        if not significant:
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
            "tackler_player_id",
            "fouler_player_id",
            "fouled_player_id",
            "assist_player_id",
        )
    }
    if profile.favorite_player_id and profile.favorite_player_id in involved:
        if not significant:
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
