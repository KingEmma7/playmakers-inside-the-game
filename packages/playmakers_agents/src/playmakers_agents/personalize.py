from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Sequence
from functools import cache
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
# across processes; the audience executor avoids repeating the last six visible lines.
FAN_LINES = {
    "en": {
        "pass": (
            "{player} plays it to {receiver}.",
            "{receiver} receives from {player}.",
            "The ball goes from {player} to {receiver}.",
            "{player}, to {receiver}.",
            "A pass to {receiver} from {player}.",
            "{player} finds {receiver}.",
            "Now {receiver}, from {player}.",
            "{receiver} gets it from {player}.",
        ),
        "incomplete": (
            "{player}'s pass does not reach {receiver}.",
            "{player} cannot find {receiver}.",
            "No completed pass from {player} to {receiver}.",
            "The pass fails to find {receiver}.",
            "No connection with {receiver}.",
            "{player} attempts to find {receiver}.",
            "That pass from {player} is incomplete.",
            "The ball does not reach {receiver}.",
        ),
        "pressure": (
            "{player} passes under pressure.",
            "Pressure on {player} as the ball moves on.",
            "{player} has company on the ball.",
            "Under pressure, {player} passes.",
            "A pass from {player} under pressure.",
            "With pressure on, {player} passes.",
            "The ball moves on under pressure.",
            "Pressure as {player} plays the ball.",
        ),
        "carry": (
            "{player} carries the ball.",
            "{player} moves with the ball.",
            "The ball stays with {player}.",
            "On the ball, {player}.",
            "A carry from {player}.",
            "In possession, {player} carries.",
            "{player} keeps hold of it.",
            "Ball at feet for {player}.",
        ),
        "shot": (
            "Chance! {player} takes a shot.",
            "{player} goes for goal.",
            "A shot from {player}!",
            "{player} with the shot!",
            "An attempt from {player}.",
            "Going for goal: {player}.",
            "Now a shot by {player}.",
            "{player} takes aim at goal.",
        ),
        "saved": (
            "Saved! {player}'s shot is stopped.",
            "{player} shoots, but the keeper saves.",
            "The keeper denies {player}.",
            "A save to deny {player}.",
            "The shot by {player} is saved.",
            "An effort from {player}, saved.",
            "Stopped: the attempt by {player}.",
            "{player} has a shot saved.",
        ),
        "foul": (
            "{player} commits a foul.",
            "A foul by {player} stops play.",
            "Play stops after {player}'s foul.",
            "Foul committed by {player}.",
            "A foul there from {player}.",
            "Play halted: a foul by {player}.",
            "{player} fouls; play stops.",
            "A stoppage for a foul by {player}.",
        ),
        "card": (
            "{player} is shown {color}.",
            "The card is {color} for {player}.",
            "The referee shows {player} {color}.",
            "A booking: {color} for {player}.",
            "Out comes {color} for {player}.",
            "Shown to {player}: {color}.",
            "The decision: {color} for {player}.",
            "For {player}, it is {color}.",
        ),
        "possession_change": (
            "{team} take possession.",
            "The ball is now with {team}.",
            "Possession goes to {team}.",
            "Now {team} have the ball.",
            "With {team} in possession.",
            "The ball changes hands to {team}.",
            "It is {team} on the ball.",
            "{team} win the ball.",
        ),
        "tackle": (
            "{player} makes a tackle.",
            "A tackle from {player}.",
            "{player} challenges for the ball.",
            "In comes a tackle by {player}.",
            "{player} puts in a tackle.",
            "A challenge from {player}.",
            "{player} goes into a tackle.",
            "Now {player} with a tackle.",
        ),
        "substitution": (
            "{player} comes on for {receiver}.",
            "{receiver} makes way for {player}.",
            "A change: {player} replaces {receiver}.",
            "On: {player}. Off: {receiver}.",
            "{player} on, {receiver} off.",
            "On comes {player} for {receiver}.",
            "Off goes {receiver}; on comes {player}.",
            "Replacing {receiver}: {player}.",
        ),
        "kickoff": (
            "{team} take the kickoff.",
            "Kickoff for {team}.",
            "{team} start from the centre.",
            "From the centre, {team} kick off.",
            "The kickoff goes to {team}.",
            "At the centre: {team} to kick off.",
            "Under way with {team} kicking off.",
            "A kickoff taken by {team}.",
        ),
        "period_start": (
            "The half begins.",
            "A new half starts.",
            "The match clock starts for this half.",
            "This half is under way.",
            "Play begins for this half.",
            "The half gets started.",
            "Time to begin the half.",
            "The start of the half.",
        ),
        "period_end": (
            "The half ends.",
            "The whistle ends the half.",
            "Play ends for this half.",
            "That is the end of the half.",
            "The half comes to a close.",
            "The whistle brings the half to an end.",
            "Time is up for this half.",
            "The half is over.",
        ),
        "tracking_frame": (
            "Player positions updated.",
            "The pitch positions refresh.",
            "A new view of the player positions.",
            "The latest player positions.",
            "An update on player positions.",
            "Positions on the pitch, updated.",
            "Here are the current positions.",
            "The player positions refresh.",
        ),
    },
    "es": {
        "pass": (
            "{player} pasa a {receiver}.",
            "{receiver} recibe de {player}.",
            "El balón va de {player} a {receiver}.",
            "Pase de {player}; recibe {receiver}.",
            "Ahora recibe {receiver}, de {player}.",
            "{player} mueve el balón hacia {receiver}.",
            "Toca {player}, recibe {receiver}.",
            "{player} pasa el balón a {receiver}.",
        ),
        "incomplete": (
            "El pase de {player} no llega a {receiver}.",
            "{player} no encuentra a {receiver}.",
            "Pase incompleto de {player} hacia {receiver}.",
            "El balón no llega a {receiver}.",
            "No conecta con {receiver}.",
            "{player} intenta buscar a {receiver}.",
            "No se completa el pase de {player}.",
            "No llega el envío a {receiver}.",
        ),
        "pressure": (
            "{player} pasa bajo presión.",
            "Presión sobre {player} al pasar.",
            "{player} tiene compañía con el balón.",
            "Bajo presión, {player} pasa.",
            "Pase de {player} con presión encima.",
            "El balón sale bajo presión.",
            "Con presión, {player} suelta el balón.",
            "Hay presión sobre {player} al pasar.",
        ),
        "carry": (
            "{player} conduce el balón.",
            "{player} avanza con el balón.",
            "El balón sigue con {player}.",
            "Con el balón, {player}.",
            "Conducción de {player}.",
            "{player} lleva el balón.",
            "Balón en los pies de {player}.",
            "Con el balón en los pies va {player}.",
        ),
        "shot": (
            "¡Ocasión! {player} dispara.",
            "{player} busca el gol.",
            "¡Disparo de {player}!",
            "¡Remate de {player}!",
            "{player} tira a puerta.",
            "Lo intenta {player}.",
            "Ahora dispara {player}.",
            "Intento de {player} a portería.",
        ),
        "saved": (
            "¡Parada! Detienen el disparo de {player}.",
            "{player} dispara, pero el portero para.",
            "El portero frena a {player}.",
            "Paran el remate de {player}.",
            "El tiro de {player} acaba en parada.",
            "Intento de {player}, detenido.",
            "Detienen el remate de {player}.",
            "Parada ante el tiro de {player}.",
        ),
        "foul": (
            "{player} comete una falta.",
            "Una falta de {player} detiene el juego.",
            "El juego se para por una falta de {player}.",
            "Falta cometida por {player}.",
            "Hay falta de {player}.",
            "Se detiene el juego: falta de {player}.",
            "{player} hace falta; se para el juego.",
            "Falta de {player}: juego detenido.",
        ),
        "card": (
            "{player} recibe {color}.",
            "Se señala {color} para {player}.",
            "El árbitro muestra {color} a {player}.",
            "Amonestación: {color} para {player}.",
            "Hay {color} para {player}.",
            "Para {player}, {color}.",
            "La decisión: {color} para {player}.",
            "Muestran {color} a {player}.",
        ),
        "possession_change": (
            "{team} toma la posesión.",
            "El balón está con {team}.",
            "La posesión pasa a {team}.",
            "Ahora tiene el balón {team}.",
            "Posesión para {team}.",
            "El balón cambia de manos: {team}.",
            "{team} se hace con el balón.",
            "Con el balón, {team}.",
        ),
        "tackle": (
            "{player} hace una entrada.",
            "Entrada de {player}.",
            "{player} disputa el balón.",
            "Llega la entrada de {player}.",
            "{player} entra a disputar el balón.",
            "Una entrada por parte de {player}.",
            "A disputar el balón va {player}.",
            "Ahora, entrada de {player}.",
        ),
        "substitution": (
            "{player} entra por {receiver}.",
            "{receiver} deja su sitio a {player}.",
            "Cambio: {player} sustituye a {receiver}.",
            "Entra {player}; sale {receiver}.",
            "{player} al campo por {receiver}.",
            "Sale {receiver}; entra {player}.",
            "En lugar de {receiver}, {player}.",
            "Relevo: {player} por {receiver}.",
        ),
        "kickoff": (
            "{team} saca del centro.",
            "Saque inicial de {team}.",
            "{team} empieza desde el centro.",
            "Desde el centro saca {team}.",
            "El saque de centro es de {team}.",
            "Balón al centro: saca {team}.",
            "Se pone en juego: saca {team}.",
            "En el centro, saque de {team}.",
        ),
        "period_start": (
            "Empieza la mitad.",
            "Comienza una nueva mitad.",
            "Arranca el reloj de esta mitad.",
            "Esta mitad ya está en marcha.",
            "Se inicia el juego de esta mitad.",
            "Arranca esta mitad.",
            "Da comienzo esta mitad.",
            "El inicio de esta mitad.",
        ),
        "period_end": (
            "Termina la mitad.",
            "El silbato cierra la mitad.",
            "Acaba el juego de esta mitad.",
            "Se cierra esta mitad.",
            "Esta mitad llega a su fin.",
            "El silbato pone fin a esta mitad.",
            "Se acaba el tiempo de esta mitad.",
            "Final de esta mitad.",
        ),
        "tracking_frame": (
            "Posiciones actualizadas.",
            "Se actualizan las posiciones del campo.",
            "Nueva vista de las posiciones.",
            "Las posiciones más recientes.",
            "Una actualización de posiciones.",
            "Posiciones en el campo, al día.",
            "Así están las posiciones ahora.",
            "Se renueva la vista de posiciones.",
        ),
    },
    "fr": {
        "pass": (
            "{player} passe à {receiver}.",
            "{receiver} reçoit de {player}.",
            "Le ballon va de {player} à {receiver}.",
            "Une passe de {player} pour {receiver}.",
            "{player} trouve {receiver} d'une passe.",
            "À {receiver}, sur une passe de {player}.",
            "{player} transmet le ballon à {receiver}.",
            "{receiver} reçoit le ballon de {player}.",
        ),
        "incomplete": (
            "La passe de {player} n'atteint pas {receiver}.",
            "{player} ne trouve pas {receiver}.",
            "Passe manquée de {player} vers {receiver}.",
            "Le ballon n'arrive pas à {receiver}.",
            "Passe ratée vers {receiver}.",
            "{player} cherche à trouver {receiver}.",
            "La passe de {player} n'aboutit pas.",
            "Le ballon ne parvient pas à {receiver}.",
        ),
        "pressure": (
            "{player} passe sous pression.",
            "Pression sur {player} au moment de passer.",
            "{player} est accompagné sur le ballon.",
            "Sous pression, {player} passe.",
            "Une passe de {player} sous pression.",
            "Le ballon circule sous pression.",
            "{player} lâche le ballon sous pression.",
            "La pression accompagne cette passe.",
        ),
        "carry": (
            "{player} conduit le ballon.",
            "{player} avance avec le ballon.",
            "Le ballon reste avec {player}.",
            "Au ballon, {player}.",
            "Une conduite de balle de {player}.",
            "{player} progresse balle au pied.",
            "Ballon au pied pour {player}.",
            "Avec le ballon, voici {player}.",
        ),
        "shot": (
            "Occasion ! {player} frappe.",
            "{player} tente sa chance.",
            "Une frappe de {player} !",
            "{player} décoche un tir !",
            "Une tentative de {player}.",
            "Tentative au but de {player}.",
            "Voici la frappe de {player}.",
            "{player} tente de marquer.",
        ),
        "saved": (
            "Arrêt ! Le tir de {player} est repoussé.",
            "{player} frappe, mais le gardien arrête.",
            "Le gardien fait obstacle à {player}.",
            "Le tir de {player} est arrêté.",
            "Un arrêt sur la frappe de {player}.",
            "Tentative de {player}, arrêtée.",
            "Arrêt sur le tir de {player}.",
            "{player} voit sa frappe arrêtée.",
        ),
        "foul": (
            "{player} commet une faute.",
            "Une faute de {player} arrête le jeu.",
            "Le jeu s'arrête après la faute de {player}.",
            "Faute commise par {player}.",
            "Il y a faute de {player}.",
            "Jeu interrompu : faute de {player}.",
            "{player} fait faute, le jeu s'arrête.",
            "Arrêt de jeu pour faute de {player}.",
        ),
        "card": (
            "{player} reçoit {color}.",
            "C'est {color} pour {player}.",
            "L'arbitre montre {color} à {player}.",
            "Sanction : {color} pour {player}.",
            "Voici {color} pour {player}.",
            "Pour {player}, ce sera {color}.",
            "La décision : {color} pour {player}.",
            "Carton pour {player} : {color}.",
        ),
        "possession_change": (
            "{team} prend possession du ballon.",
            "Le ballon est avec {team}.",
            "La possession passe à {team}.",
            "Place à {team} avec le ballon.",
            "Ballon désormais pour {team}.",
            "Le ballon change de camp : {team}.",
            "{team} récupère la possession.",
            "En possession : {team}.",
        ),
        "tackle": (
            "{player} effectue un tacle.",
            "Un tacle de {player}.",
            "{player} dispute le ballon.",
            "Voici le tacle de {player}.",
            "{player} intervient avec un tacle.",
            "Une intervention de {player}.",
            "À la lutte pour le ballon : {player}.",
            "Au tacle, voici {player}.",
        ),
        "substitution": (
            "{player} entre pour {receiver}.",
            "{receiver} cède sa place à {player}.",
            "Changement : {player} remplace {receiver}.",
            "Entrée de {player}, sortie de {receiver}.",
            "{player} prend le relais de {receiver}.",
            "Place à {player} pour {receiver}.",
            "Pour remplacer {receiver} : {player}.",
            "Relais : {player} pour {receiver}.",
        ),
        "kickoff": (
            "{team} donne le coup d'envoi.",
            "Coup d'envoi pour {team}.",
            "{team} part du centre.",
            "Du centre, coup d'envoi de {team}.",
            "Au centre : coup d'envoi pour {team}.",
            "Le coup d'envoi revient à {team}.",
            "C'est {team} qui engage.",
            "Engagement au centre pour {team}.",
        ),
        "period_start": (
            "La mi-temps commence.",
            "Une nouvelle mi-temps débute.",
            "Le chrono démarre pour cette mi-temps.",
            "Cette période est en cours.",
            "Le jeu débute pour cette période.",
            "Début de cette période.",
            "Cette période démarre.",
            "Place au jeu pour cette période.",
        ),
        "period_end": (
            "La mi-temps se termine.",
            "Le sifflet termine la mi-temps.",
            "Fin du jeu pour cette mi-temps.",
            "Cette période prend fin.",
            "La fin de cette période est sifflée.",
            "Le jeu est terminé pour cette période.",
            "Le temps est écoulé pour cette période.",
            "Cette période est terminée.",
        ),
        "tracking_frame": (
            "Positions actualisées.",
            "Les positions sur le terrain sont actualisées.",
            "Nouvelle vue des positions.",
            "Les dernières positions sur le terrain.",
            "Un point sur les positions.",
            "Positions sur le terrain à jour.",
            "Voici les positions actuelles.",
            "La vue des positions se renouvelle.",
        ),
    },
}


GOAL_THREAT_LINES = {
    "en": (
        "{name} are building pressure.",
        "{name} are pinning them back.",
        "Sustained pressure from {name}.",
        "{name} keep pushing forward.",
    ),
    "es": (
        "{name} aumenta la presión.",
        "{name} mantiene la presión.",
        "Presión sostenida de {name}.",
        "{name} sigue en ataque.",
    ),
    "fr": (
        "{name} accentue la pression.",
        "{name} maintient la pression.",
        "Pression soutenue de {name}.",
        "{name} continue de pousser.",
    ),
}


def goal_threat_phrase(
    event_id: str, name: str, language: Literal["en", "es", "fr"], previous: str = ""
) -> str:
    variants = GOAL_THREAT_LINES[language]
    offset = hashlib.sha256(event_id.encode()).digest()[0] % len(variants)
    headline = variants[offset].format(name=name)
    if headline == previous:
        headline = variants[(offset + 1) % len(variants)].format(name=name)
    return headline


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


@cache
def _fan_pattern(template: str) -> re.Pattern[str]:
    literals = re.split(r"\{[^{}]+\}", template)
    return re.compile(r"\A" + ".+?".join(re.escape(part) for part in literals) + r"\Z")


def fan_phrase(
    event: MatchEvent,
    language: Literal["en", "es", "fr"],
    previous: str = "",
    recent: Sequence[str] = (),
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
    prefix = {"en": "Favourite: ", "es": "Favorito: ", "fr": "Favori: "}[language]
    excluded = {line.removeprefix(prefix).removeprefix(prefix) for line in (*recent[-6:], previous)}
    for step in range(len(variants)):
        variant = variants[(offset + step) % len(variants)]
        if not any(_fan_pattern(variant).fullmatch(line) for line in excluded):
            return variant.format(**values), ""
    return variants[offset].format(**values), ""


async def personalize(
    cue: OverlayCue,
    profile: ViewerProfile,
    event: MatchEvent,
    client: BaseChatClient,
    index: int,
    timeout: float = 1.5,
    previous: str = "",
    recent: Sequence[str] = (),
) -> OverlayCue:
    payload: dict[str, Any] = dict(cue.payload)
    team_label = player_label = {"en": "Favourite", "es": "Favorito", "fr": "Favori"}[
        profile.language
    ]
    significant = payload.get("moment") in ("goal", "card")
    if profile.persona == "casual":
        if cue.template != "what_if" and not significant:
            headline, detail = fan_phrase(event, profile.language, previous, recent)
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
