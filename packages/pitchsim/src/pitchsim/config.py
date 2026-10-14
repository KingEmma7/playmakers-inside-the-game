from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TeamStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "balanced"

    tempo: float = Field(default=1.0, ge=0.5, le=1.6, description="Higher = more events.")
    directness: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Higher = longer, more vertical passes."
    )
    press_intensity: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Higher = more turnovers forced."
    )
    pass_risk: float = Field(default=0.5, ge=0.0, le=1.0, description="Higher = riskier passes.")
    discipline: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Higher = fewer fouls/cards."
    )
    counter_attack: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Higher = faster attacks after turnovers."
    )


class StoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minute: int = Field(ge=0, le=120)
    type: Literal["press_collapse", "red_card", "goal_boost"]  # minimal v1
    team: Literal["home", "away"]
    label: str | None = None


class MatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: int = 0
    home_style: TeamStyle = Field(default_factory=lambda: TeamStyle(name="possession", tempo=1.05))
    away_style: TeamStyle = Field(default_factory=lambda: TeamStyle(name="counter", tempo=1.0))
    story: list[StoryEvent] = Field(default_factory=list)
