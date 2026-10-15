from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlaymakersStatsBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(PlaymakersStatsBaseModel):
    event_ids: list[str] = Field(default_factory=list)


class PossessionResult(PlaymakersStatsBaseModel):
    home_possession: float = Field(ge=0.0, le=1.0)
    away_possession: float = Field(ge=0.0, le=1.0)
    evidence: Evidence


class PressureIndexResult(PlaymakersStatsBaseModel):
    team_id: str
    pressure_index: float = Field(ge=0.0, le=1.0, description="0..1 pressure proxy over a window.")
    evidence: Evidence


class PassDifficultyResult(PlaymakersStatsBaseModel):
    event_id: str
    difficulty: float = Field(ge=0.0, le=1.0)
    pressure: float = Field(ge=0.0, le=1.0)
    completed: bool
    evidence: Evidence


class XGResult(PlaymakersStatsBaseModel):
    event_id: str
    xg: float = Field(ge=0.0, le=1.0)
    outcome: Literal["goal", "saved", "blocked", "off_target", "woodwork"]
    evidence: Evidence


class MomentumResult(PlaymakersStatsBaseModel):
    home_momentum: float = Field(ge=-1.0, le=1.0, description="-1..1 where + favors home.")
    away_momentum: float = Field(ge=-1.0, le=1.0, description="-1..1 where + favors away.")
    evidence: Evidence
