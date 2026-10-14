from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GalleryContractsBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewerProfile(GalleryContractsBaseModel):
    persona: Literal["analyst", "casual"] = "analyst"
    favorite_team_id: str | None = None
    favorite_player_id: str | None = None
    language: Literal["en", "es"] = "en"


class Insight(GalleryContractsBaseModel):
    insight_id: str
    clock_ms: int = Field(ge=0)
    kind: Literal["tactics", "storyline", "what_if", "stats"]
    headline: str
    detail: str
    evidence_event_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class OverlayCue(GalleryContractsBaseModel):
    cue_id: str
    clock_ms: int = Field(ge=0)
    template: str
    payload: dict[str, Any]
    duration_ms: int = Field(default=4000, ge=250, le=30_000)
    priority: int = Field(default=0, ge=0, le=100)
    evidence_event_ids: list[str] = Field(default_factory=list)
    persona: Literal["analyst", "casual"] | None = None
    language: Literal["en", "es"] | None = None


class ComplianceDecision(GalleryContractsBaseModel):
    ok: bool
    reasons: list[str] = Field(default_factory=list)
