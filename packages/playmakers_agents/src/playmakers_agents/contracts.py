from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlaymakersContractsBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewerProfile(PlaymakersContractsBaseModel):
    persona: Literal["analyst", "casual"] = "analyst"
    favorite_team_id: str | None = None
    favorite_player_id: str | None = None
    language: Literal["en", "es", "fr"] = "en"


class Insight(PlaymakersContractsBaseModel):
    insight_id: str
    clock_ms: int = Field(ge=0)
    kind: Literal["tactics", "storyline", "what_if", "stats"]
    headline: str
    detail: str
    evidence_event_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class CueProvenance(PlaymakersContractsBaseModel):
    agent: Literal["tactics", "storyline", "what_if", "graphics"]
    source: Literal["agent", "template", "simulation"]
    compliance: Literal["verified", "template_fallback", "not_reviewed"]
    attempts: int = Field(default=1, ge=1)
    reasons: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    metric_evidence: dict[str, list[str]] = Field(default_factory=dict)
    insight_headline: str | None = None
    personalized_for: Literal["analyst", "casual"] | None = None


class OverlayCue(PlaymakersContractsBaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    layer: Literal["lower_third", "score_bug", "full_screen"] = "lower_third"
    safe_area: Literal["broadcast_safe"] = "broadcast_safe"
    cue_id: str
    clock_ms: int = Field(ge=0)
    template: str
    payload: dict[str, Any]
    duration_ms: int = Field(default=4000, ge=250, le=30_000)
    priority: int = Field(default=0, ge=0, le=100)
    evidence_event_ids: list[str] = Field(min_length=1)
    persona: Literal["analyst", "casual"] | None = None
    language: Literal["en", "es", "fr"] | None = None
    provenance: CueProvenance | None = None


class ComplianceDecision(PlaymakersContractsBaseModel):
    ok: bool
    reasons: list[str] = Field(default_factory=list)


class AgentTraceEvent(PlaymakersContractsBaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    agent: str
    action: str
    latency_ms: float = Field(ge=0)
    status: Literal["ok", "rejected", "retry", "fallback", "error"] = "ok"
