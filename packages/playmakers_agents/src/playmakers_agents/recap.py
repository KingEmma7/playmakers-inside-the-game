from __future__ import annotations

from typing import Literal

from playmakers_schema.models import CardEvent, GoalEvent, MatchEvent, ShotEvent
from pydantic import BaseModel

from playmakers_agents.contracts import Insight

TEAM_NAMES = {"HOME": "Northbridge Rovers", "AWAY": "Southport Athletic"}
BIG_CHANCE_XG = 0.3
MAX_MOMENTS = 6
MIN_MOMENTS = 4
Language = Literal["en", "es", "fr"]
Persona = Literal["analyst", "casual"]


class RecapMoment(BaseModel):
    clock_ms: int
    event_id: str
    kind: Literal["goal", "red_card", "big_chance", "chance"]
    team_id: str | None
    player_id: str | None
    xg: float | None = None


def team_name(team_id: str | None) -> str:
    return TEAM_NAMES["HOME" if team_id and team_id.endswith("_HOME") else "AWAY"]


def score(events: list[MatchEvent]) -> tuple[int, int]:
    goals = [e for e in events if isinstance(e, GoalEvent)]
    home = sum(e.scoring_team_id.endswith("_HOME") for e in goals)
    return home, len(goals) - home


def key_moments(events: list[MatchEvent]) -> list[RecapMoment]:
    decisive: list[RecapMoment] = []
    chances: list[RecapMoment] = []
    for e in events:
        if isinstance(e, GoalEvent):
            decisive.append(
                RecapMoment(
                    clock_ms=e.clock_ms,
                    event_id=e.event_id,
                    kind="goal",
                    team_id=e.scoring_team_id,
                    player_id=e.scorer_player_id,
                )
            )
        elif isinstance(e, CardEvent) and e.color == "red":
            decisive.append(
                RecapMoment(
                    clock_ms=e.clock_ms,
                    event_id=e.event_id,
                    kind="red_card",
                    team_id=e.team_id,
                    player_id=e.carded_player_id,
                )
            )
        elif isinstance(e, ShotEvent) and e.outcome != "goal":
            chances.append(
                RecapMoment(
                    clock_ms=e.clock_ms,
                    event_id=e.event_id,
                    kind="big_chance" if e.xg > BIG_CHANCE_XG else "chance",
                    team_id=e.team_id,
                    player_id=e.shooter_player_id,
                    xg=round(e.xg, 2),
                )
            )
    chances.sort(key=lambda m: m.xg or 0, reverse=True)
    big = [m for m in chances if m.kind == "big_chance"]
    rest = [m for m in chances if m.kind == "chance"]
    picked = decisive[:MAX_MOMENTS]
    picked += big[: MAX_MOMENTS - len(picked)]
    picked += rest[: max(0, MIN_MOMENTS - len(picked))]
    return sorted(picked, key=lambda m: m.clock_ms)


def recap_text(home: int, away: int, language: Language, persona: Persona) -> tuple[str, str]:
    h, a = TEAM_NAMES["HOME"], TEAM_NAMES["AWAY"]
    winner = h if home > away else a if away > home else None
    headline = {
        "en": f"Full time: {h} {home}–{away} {a}",
        "es": f"Final: {h} {home}–{away} {a}",
        "fr": f"Fin du match : {h} {home}–{away} {a}",
    }[language]
    if persona == "analyst":
        detail = {
            "en": f"{winner} take the points." if winner else "The points are shared.",
            "es": f"{winner} se lleva los puntos." if winner else "Reparto de puntos.",
            "fr": f"{winner} prend les points." if winner else "Les points sont partagés.",
        }[language]
        detail += {
            "en": " Every moment below is a verified match event.",
            "es": " Cada momento es un evento verificado del partido.",
            "fr": " Chaque moment est un événement vérifié du match.",
        }[language]
    else:
        detail = {
            "en": f"What a game! {winner} win it." if winner else "What a game! Honours even.",
            "es": f"¡Qué partido! Gana {winner}." if winner else "¡Qué partido! Empate.",
            "fr": f"Quel match ! Victoire de {winner}." if winner else "Quel match ! Match nul.",
        }[language]
    return headline, detail


def localized_recap(
    base: Insight, home: int, away: int, language: Language, persona: Persona
) -> Insight:
    if language == "en" and persona == "analyst":
        return base
    headline, detail = recap_text(home, away, language, persona)
    return base.model_copy(update={"headline": headline, "detail": detail})
