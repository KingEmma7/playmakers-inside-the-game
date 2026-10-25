"""Prefix-only next-five-minute scoring probability, fitted to synthetic PitchSim."""

from __future__ import annotations

from collections import deque
from math import exp
from typing import Literal

from playmakers_schema.models import MatchEvent
from pydantic import BaseModel, ConfigDict, Field

from playmakers_stats.types import Evidence

WINDOW_MS = 300_000
FEATURE_NAMES = (
    "entries",
    "box_actions",
    "shots",
    "xg",
    "third_share",
    "high_wins",
    "third_completions",
    "territory",
)
# Replaced reproducibly by scripts/calibrate_threat.py --fit.
COEFFICIENTS = (
    -2.9210297355,
    0.2933119107,
    0.1954572702,
    0.2024326988,
    -0.5208620475,
    0.1424340832,
    -0.3269378625,
    0.0943204256,
    0.2960794962,
)
BAND_THRESHOLDS = (0.06537326686186828, 0.07398210085765804)


class GoalThreat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_id: str
    probability: float = Field(ge=0, le=1)
    level: Literal["Low", "Medium", "High"]
    horizon_ms: Literal[300000] = 300_000
    features: dict[str, float]
    evidence: Evidence


class ThreatTracker:
    """Bounded rolling event features; never reads labels, future events or shot outcomes.

    PitchSim home attacks increasing x throughout both halves. A goal resets both
    teams; its associated shot is removed too. No scoring event is a predictor.
    """

    def __init__(self) -> None:
        self.rows: deque[tuple[int, str, str, tuple[float, ...]]] = deque()
        self.clock_ms = 0
        self.last_sequence = -1
        self.match_id: str | None = None

    def ingest(self, event: MatchEvent) -> None:
        if self.match_id not in (None, event.match_id) or event.sequence <= self.last_sequence:
            raise ValueError("ThreatTracker requires one ordered match")
        self.match_id, self.last_sequence = event.match_id, event.sequence
        self.clock_ms = event.clock_ms
        while self.rows and self.rows[0][0] < event.clock_ms - WINDOW_MS:
            self.rows.popleft()
        if event.event_type in ("goal", "period_start"):
            self.rows.clear()
            return
        team = event.team_id
        if event.event_type == "possession_change":
            team = event.to_team_id
        if not team:
            return
        pos = (
            getattr(event, "end_position", None)
            or getattr(event, "position", None)
            or getattr(event, "ball_position", None)
        )
        if pos is None or event.event_type not in (
            "pass",
            "carry",
            "shot",
            "tackle",
            "possession_change",
        ):
            return
        x = pos.x if team.endswith("_HOME") else 105 - pos.x
        start = getattr(event, "start_position", pos)
        sx = start.x if team.endswith("_HOME") else 105 - start.x
        completed = event.event_type == "carry" or (event.event_type == "pass" and event.completed)
        third = float(completed and x >= 70)
        values = (
            float(completed and sx < 70 <= x),
            float(completed and x >= 88.5 and 13.84 <= pos.y <= 54.16),
            float(event.event_type == "shot"),
            float(event.xg) if event.event_type == "shot" else 0.0,
            third,
            float(
                x > 52.5
                and (
                    (event.event_type == "tackle" and event.won_ball)
                    or (
                        event.event_type == "possession_change"
                        and event.reason not in ("goal", "foul")
                    )
                )
            ),
            float(event.event_type == "pass" and event.completed and x >= 70),
            x / 105,
        )
        self.rows.append((event.clock_ms, event.event_id, team, values))

    def predict(self, team_id: str, match_clock_ms: int | None = None) -> GoalThreat:
        now = self.clock_ms if match_clock_ms is None else match_clock_ms
        if now < self.clock_ms:
            raise ValueError("Historical queries require replaying the event prefix")
        sums = [0.0] * len(FEATURE_NAMES)
        total_third = 0.0
        ids: list[str] = []
        latest = 0.5
        for clock, eid, team, values in self.rows:
            if not now - WINDOW_MS <= clock <= now:
                continue
            weight = exp(-(now - clock) / 180_000)
            total_third += values[4] * weight
            if team == team_id or values[4]:
                ids.append(eid)
            if team == team_id:
                for i, value in enumerate(values):
                    sums[i] += value * weight
                latest = values[-1] * weight + 0.5 * (1 - weight)
        sums[4] /= max(1.0, total_third)
        sums[-1] = latest
        # Counts scaled to keep fitting well conditioned; all transformations fixed.
        scales = (5, 5, 2, 1, 1, 5, 10, 1)
        features = {
            name: value / scale
            for name, value, scale in zip(FEATURE_NAMES, sums, scales, strict=True)
        }
        z = COEFFICIENTS[0] + sum(
            c * v for c, v in zip(COEFFICIENTS[1:], features.values(), strict=True)
        )
        p = 1 / (1 + exp(-max(-30, min(30, z))))
        level = (
            "High" if p >= BAND_THRESHOLDS[1] else "Medium" if p >= BAND_THRESHOLDS[0] else "Low"
        )
        return GoalThreat(
            team_id=team_id,
            probability=p,
            level=level,
            features=features,
            evidence=Evidence(event_ids=ids),
        )


class ThreatAnnouncements:
    """Enter High once, rearm below Medium; three match minute cooldown per team."""

    def __init__(self) -> None:
        self.high: set[str] = set()
        self.last: dict[str, int] = {}

    def update(self, threat: GoalThreat, clock_ms: int) -> bool:
        team = threat.team_id
        if threat.probability < BAND_THRESHOLDS[0]:
            self.high.discard(team)
        if threat.level != "High" or team in self.high:
            return False
        self.high.add(team)
        if not threat.evidence.event_ids or clock_ms - self.last.get(team, -WINDOW_MS) < 180_000:
            return False
        self.last[team] = clock_ms
        return True
