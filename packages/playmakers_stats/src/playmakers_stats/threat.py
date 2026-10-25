"""Prefix-only scoring probability, fitted to synthetic PitchSim."""

from __future__ import annotations

from collections import deque
from math import exp, hypot
from typing import Literal

from playmakers_schema.models import MatchEvent
from pydantic import BaseModel, ConfigDict, Field

from playmakers_stats.types import Evidence

WINDOW_MS = 300_000
HORIZON_MS = 120_000
COOLDOWN_MS = 600_000
FEATURE_NAMES = (
    "possession",
    "territory",
    "possession_territory",
    "goal_proximity",
    "central_box",
    "attacking_third",
    "third_spell",
    "last_five_territory",
    "third_seconds",
    "entries",
    "shots",
    "xg",
)
# Replaced reproducibly by scripts/calibrate_threat.py --fit.
COEFFICIENTS = (
    -4.0493423422,
    0.1550327826,
    0.7691634777,
    0.1744049859,
    1.36556686,
    0.887465536,
    -0.0785956736,
    0.2483636707,
    -0.3611696465,
    0.2011619544,
    -0.1135153728,
    -0.0968485985,
    0.1517067988,
)
BAND_THRESHOLDS = (0.023521929166955977, 0.06746503590763081)


class GoalThreat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_id: str
    probability: float = Field(ge=0, le=1)
    level: Literal["Low", "Medium", "High"]
    horizon_ms: Literal[120000] = HORIZON_MS
    features: dict[str, float]
    evidence: Evidence


class ThreatTracker:
    """Observed possession and geometry plus bounded history; no future/outcome reads.

    Home attacks increasing x in both halves. Shots end the observed spell for
    every outcome; the next possession event supplies the actual restart position.
    Goals reset history, removing the associated shot as well.
    """

    def __init__(self) -> None:
        # clock, evidence ID, possession team, physical x/y, shot xG, third entry,
        # seconds spent in that team's attacking third before this observation.
        self.rows: deque[tuple[int, str, str, float, float, float, float, float]] = deque()
        self.clock_ms = 0
        self.last_sequence = -1
        self.match_id: str | None = None
        self.owner: str | None = None
        self.ball = (52.5, 34.0)
        self.state_clock = 0
        self.third_since: int | None = None

    @staticmethod
    def territory(team: str, x: float) -> float:
        return x if team.endswith("_HOME") else 105 - x

    def ingest(self, event: MatchEvent) -> None:
        if self.match_id not in (None, event.match_id) or event.sequence <= self.last_sequence:
            raise ValueError("ThreatTracker requires one ordered match")
        self.match_id, self.last_sequence = event.match_id, event.sequence
        self.clock_ms = event.clock_ms
        while self.rows and self.rows[0][0] < event.clock_ms - WINDOW_MS:
            self.rows.popleft()
        if event.event_type in ("goal", "period_start"):
            self.rows.clear()
            self.owner, self.third_since = None, None
            self.ball = (52.5, 34.0)
            self.state_clock = event.clock_ms
            return
        kind = event.event_type
        if kind not in ("kickoff", "pass", "carry", "shot", "possession_change", "tackle"):
            return
        if kind == "tackle" and not event.won_ball:
            return
        team = event.to_team_id if kind == "possession_change" else event.team_id
        pos = (
            getattr(event, "end_position", None)
            or getattr(event, "position", None)
            or getattr(event, "ball_position", None)
            or getattr(event, "start_position", None)
        )
        if not team or pos is None:
            return
        old_owner = self.owner
        old_third = self.owner and self.territory(self.owner, self.ball[0]) >= 70
        duration = min(60.0, (event.clock_ms - self.state_clock) / 1000) if old_third else 0.0
        # Attribute elapsed time to the old owner, separately from this new observation.
        if duration and self.rows:
            last = self.rows[-1]
            self.rows[-1] = (*last[:7], last[7] + duration)
        x = self.territory(team, pos.x)
        entry = float(x >= 70 and (self.owner != team or not old_third))
        self.rows.append(
            (
                event.clock_ms,
                event.event_id,
                team,
                pos.x,
                pos.y,
                float(event.xg) if kind == "shot" else 0.0,
                entry,
                0.0,
            )
        )
        self.state_clock = event.clock_ms
        self.ball = (pos.x, pos.y)
        self.owner = None if kind == "shot" or (kind == "pass" and not event.completed) else team
        if self.owner and x >= 70:
            if self.third_since is None or not old_third or old_owner != team:
                self.third_since = event.clock_ms
        else:
            self.third_since = None

    def predict(self, team_id: str, match_clock_ms: int | None = None) -> GoalThreat:
        now = self.clock_ms if match_clock_ms is None else match_clock_ms
        if now < self.clock_ms:
            raise ValueError("Historical queries require replaying the event prefix")
        rows = [row for row in self.rows if now - WINDOW_MS <= row[0] <= now]
        own = float(self.owner == team_id)
        x = self.territory(team_id, self.ball[0])
        lateral = abs(self.ball[1] - 34)
        sums = [0.0] * 4
        for clock, _, team, _, _, xg, entry, seconds in rows:
            if team == team_id:
                weight = exp(-(now - clock) / 60_000)
                sums[0] += seconds * weight / 60
                sums[1] += entry * weight / 3
                sums[2] += float(xg > 0) * weight
                sums[3] += xg * weight
        if own and self.third_since is not None:
            sums[0] += min(60_000, now - self.state_clock) / 60_000
        recent = rows[-5:]
        features = dict(
            zip(
                FEATURE_NAMES,
                (
                    own,
                    x / 105,
                    own * x / 105,
                    own * exp(-hypot(105 - x, lateral) / 25),
                    own * float(x > 88.5 and lateral < 11),
                    own * float(x >= 70),
                    own * min(3.0, (now - self.third_since) / 60_000)
                    if self.third_since is not None
                    else 0.0,
                    sum(self.territory(team_id, row[3]) / 105 for row in recent) / len(recent)
                    if recent
                    else 0.5,
                    *sums,
                ),
                strict=True,
            )
        )
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
            evidence=Evidence(event_ids=[row[1] for row in rows]),
        )


class ThreatAnnouncements:
    """Enter High once, rearm below Medium; ten match minute cooldown per team."""

    def __init__(self) -> None:
        self.high: set[str] = set()
        self.last: dict[str, int] = {}

    def update(self, threat: GoalThreat, clock_ms: int) -> bool:
        team = threat.team_id
        if threat.probability < BAND_THRESHOLDS[0]:
            self.high.discard(team)
        if threat.level != "High" or team in self.high:
            return False
        if (
            not threat.evidence.event_ids
            or clock_ms - self.last.get(team, -COOLDOWN_MS) < COOLDOWN_MS
        ):
            return False
        self.high.add(team)
        self.last[team] = clock_ms
        return True
