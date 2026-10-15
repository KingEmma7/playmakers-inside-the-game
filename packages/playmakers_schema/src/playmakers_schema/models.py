from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SchemaVersion = Literal["1.0.0"]


class PlaymakersBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vec2(PlaymakersBaseModel):
    x: float = Field(ge=0.0, le=105.0, description="Pitch x-coordinate in meters (0..105).")
    y: float = Field(ge=0.0, le=68.0, description="Pitch y-coordinate in meters (0..68).")


class MatchEventBase(PlaymakersBaseModel):
    schema_version: SchemaVersion = "1.0.0"
    event_id: str = Field(description="Stable event identifier (UUID or deterministic string).")
    match_id: str = Field(description="Match identifier.")
    sequence: int = Field(ge=0, description="Monotonic event counter within a match.")

    clock_ms: int = Field(
        ge=0,
        description="Match clock in milliseconds since kickoff of the current match (continuous).",
    )
    period: Literal[1, 2] = Field(description="Match period (1 or 2).")

    team_id: str | None = Field(
        default=None, description="Team responsible for the action (if any)."
    )
    player_id: str | None = Field(
        default=None, description="Primary player responsible for the action (if any)."
    )

    labels: list[str] = Field(
        default_factory=list,
        description="Ground-truth labels (e.g. planted story moments) for evals.",
    )
    ground_truth: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured ground-truth payload for evaluation and agent testing.",
    )


class PeriodStartEvent(MatchEventBase):
    event_type: Literal["period_start"] = "period_start"


class PeriodEndEvent(MatchEventBase):
    event_type: Literal["period_end"] = "period_end"


class KickoffEvent(MatchEventBase):
    event_type: Literal["kickoff"] = "kickoff"
    start_position: Vec2 = Field(description="Ball position at kickoff.")


class PossessionChangeEvent(MatchEventBase):
    event_type: Literal["possession_change"] = "possession_change"
    from_team_id: str | None = None
    to_team_id: str | None = None
    reason: str = Field(description="Why possession changed (turnover, goal, foul, etc).")
    ball_position: Vec2


class PassEvent(MatchEventBase):
    event_type: Literal["pass"] = "pass"
    from_player_id: str
    to_player_id: str
    start_position: Vec2
    end_position: Vec2
    distance_m: float = Field(ge=0.0)
    completed: bool

    pressure: float = Field(ge=0.0, le=1.0, description="0..1 defensive pressure on passer.")
    difficulty: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1 pass difficulty proxy (lane openness × distance × pressure).",
    )


class CarryEvent(MatchEventBase):
    event_type: Literal["carry"] = "carry"
    start_position: Vec2
    end_position: Vec2
    distance_m: float = Field(ge=0.0)
    pressure: float = Field(ge=0.0, le=1.0)


class TackleEvent(MatchEventBase):
    event_type: Literal["tackle"] = "tackle"
    tackler_player_id: str
    target_player_id: str
    position: Vec2
    won_ball: bool


class FoulEvent(MatchEventBase):
    event_type: Literal["foul"] = "foul"
    fouler_player_id: str
    fouled_player_id: str
    position: Vec2
    card_awarded: Literal["none", "yellow", "red"] = "none"


class CardEvent(MatchEventBase):
    event_type: Literal["card"] = "card"
    carded_player_id: str
    color: Literal["yellow", "red"]
    reason: str


class SubstitutionEvent(MatchEventBase):
    event_type: Literal["substitution"] = "substitution"
    team_id: str
    player_out_id: str
    player_in_id: str
    reason: str = "tactical"


class ShotEvent(MatchEventBase):
    event_type: Literal["shot"] = "shot"
    shooter_player_id: str
    position: Vec2
    body_part: Literal["left_foot", "right_foot", "head", "other"] = "right_foot"
    xg: float = Field(ge=0.0, le=1.0)
    outcome: Literal["goal", "saved", "blocked", "off_target", "woodwork"]
    shot_speed_kmh: float | None = Field(default=None, ge=0.0)


class GoalEvent(MatchEventBase):
    event_type: Literal["goal"] = "goal"
    scoring_team_id: str
    scorer_player_id: str
    assist_player_id: str | None = None
    shot_event_id: str = Field(description="event_id of the associated shot.")


class TrackingPlayerState(PlaymakersBaseModel):
    player_id: str
    team_id: str
    position: Vec2
    vx: float = Field(description="Velocity x in m/s.")
    vy: float = Field(description="Velocity y in m/s.")


class TrackingFrameEvent(MatchEventBase):
    event_type: Literal["tracking_frame"] = "tracking_frame"
    ball_position: Vec2
    players: list[TrackingPlayerState]


MatchEvent = Annotated[
    PeriodStartEvent
    | PeriodEndEvent
    | KickoffEvent
    | PossessionChangeEvent
    | PassEvent
    | CarryEvent
    | TackleEvent
    | FoulEvent
    | CardEvent
    | SubstitutionEvent
    | ShotEvent
    | GoalEvent
    | TrackingFrameEvent,
    Field(discriminator="event_type"),
]
