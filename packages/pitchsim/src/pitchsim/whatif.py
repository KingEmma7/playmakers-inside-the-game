from __future__ import annotations

import random
from dataclasses import replace
from typing import Literal

from playmakers_schema.models import MatchEvent, Vec2
from pydantic import BaseModel, ConfigDict, Field

from pitchsim.config import StoryEvent, TeamStyle
from pitchsim.shape import carry_target, pass_target, restart_after_shot, shot_bonus, squeeze
from pitchsim.sim import (
    BASE_EVENT_RATE_PER_S,
    MATCH_MS,
    Team,
    _apply_story,
    _clamp,
    _expovariate_ms,
    _sample_ball_start,
    _turnover_ball,
    _xg_from_position,
)


class MatchSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    match_id: str
    clock_ms: int = Field(ge=0, le=MATCH_MS)
    possession: Literal["home", "away"]
    ball: Vec2
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    home_style: TeamStyle
    away_style: TeamStyle
    story: list[StoryEvent] = Field(default_factory=list)


def snapshot_from_events(
    events: list[MatchEvent],
    *,
    home_style: TeamStyle,
    away_style: TeamStyle,
    story: list[StoryEvent] | None = None,
) -> MatchSnapshot:
    if not events:
        raise ValueError("Cannot snapshot empty event list.")
    last = events[-1]
    match_id = last.match_id  # type: ignore[attr-defined]

    home_score = 0
    away_score = 0
    possession = "home"
    ball = Vec2(x=52.5, y=34.0)
    pending = sorted(story or [], key=lambda change: change.minute)
    recorded = any((e.ground_truth or {}).get("style_changes") for e in events)

    for e in events:
        changes = [
            StoryEvent.model_validate(raw)
            for raw in (e.ground_truth or {}).get("style_changes", [])
        ]
        if not recorded:
            while pending and pending[0].minute * 60000 <= e.clock_ms:
                changes.append(pending.pop(0))
        for change in changes:
            if change.team == "home":
                home_style, _ = _apply_story(home_style, change)
            else:
                away_style, _ = _apply_story(away_style, change)
        t = e.event_type  # type: ignore[attr-defined]
        if t == "card" and e.color == "red":
            if (e.team_id or "").endswith("_HOME"):
                home_style, _ = _apply_story(
                    home_style, StoryEvent(minute=0, type="red_card", team="home")
                )
            else:
                away_style, _ = _apply_story(
                    away_style, StoryEvent(minute=0, type="red_card", team="away")
                )
        if t == "goal":
            if e.scoring_team_id.endswith("_HOME"):
                home_score += 1
            elif e.scoring_team_id.endswith("_AWAY"):
                away_score += 1
        if t in ("pass", "carry"):
            ball = e.end_position
            possession = "home" if (e.team_id or "").endswith("_HOME") else "away"
        if t == "shot":
            ball = e.position
            possession = "home" if (e.team_id or "").endswith("_HOME") else "away"
        if t == "possession_change":
            bp = e.ball_position
            ball = bp
            team = e.to_team_id
            possession = "home" if (team or "").endswith("_HOME") else "away"

    return MatchSnapshot(
        match_id=match_id,
        clock_ms=int(last.clock_ms),  # type: ignore[attr-defined]
        possession=possession,
        ball=ball,
        home_score=home_score,
        away_score=away_score,
        home_style=home_style,
        away_style=away_style,
        story=[change for change in pending if change.minute * 60000 > last.clock_ms],
    )


def rollout_from_snapshot(snapshot: MatchSnapshot, *, rollout_seed: int) -> tuple[int, int]:
    """
    Monte Carlo continuation from a match snapshot. This is an approximation:
    it continues the same event model but re-seeds randomness for the remainder.
    """
    rng = random.Random(rollout_seed)
    match_id = snapshot.match_id

    home = Team(
        team_id=f"{match_id}_HOME",
        name="Northbridge Rovers",
        style=snapshot.home_style,
        player_ids=[f"{match_id}_H{idx:02d}" for idx in range(1, 12)],
        bench_ids=[f"{match_id}_H{idx:02d}" for idx in range(12, 19)],
    )
    away = Team(
        team_id=f"{match_id}_AWAY",
        name="Southport Athletic",
        style=snapshot.away_style,
        player_ids=[f"{match_id}_A{idx:02d}" for idx in range(1, 12)],
        bench_ids=[f"{match_id}_A{idx:02d}" for idx in range(12, 19)],
    )

    possession = snapshot.possession
    ball = snapshot.ball
    home_score = snapshot.home_score
    away_score = snapshot.away_score

    clock_ms = snapshot.clock_ms
    subs_home = 0
    subs_away = 0

    def team_for(pos: str) -> Team:
        return home if pos == "home" else away

    def opp_for(pos: str) -> Team:
        return away if pos == "home" else home

    pending = sorted(snapshot.story, key=lambda change: change.minute)
    while clock_ms < MATCH_MS:
        minute = clock_ms // 60000
        while pending and pending[0].minute <= minute:
            change = pending.pop(0)
            target = home if change.team == "home" else away
            updated, _ = _apply_story(target.style, change)
            if change.team == "home":
                home = replace(home, style=updated)
            else:
                away = replace(away, style=updated)

        this_team = team_for(possession)
        opp_team = opp_for(possession)

        tempo = _clamp(0.5 * (this_team.style.tempo + opp_team.style.tempo), 0.5, 1.6)
        rate = BASE_EVENT_RATE_PER_S * tempo
        clock_ms = min(MATCH_MS, clock_ms + max(50, _expovariate_ms(rng, rate)))

        if 60 <= minute <= 85 and rng.random() < 0.03:
            if possession == "home" and subs_home < 3 and this_team.bench_ids:
                subs_home += 1
                continue
            if possession == "away" and subs_away < 3 and this_team.bench_ids:
                subs_away += 1
                continue

        pass_p = 0.78
        carry_p = 0.13
        foul_p = 0.044 * (1.0 - this_team.style.discipline)
        shot_p = 0.006 + shot_bonus(ball, home=possession == "home")
        pass_p += 0.06 * (1.0 - this_team.style.directness)
        carry_p += 0.04 * (1.0 - this_team.style.directness)
        shot_p += 0.006 * this_team.style.directness
        total = pass_p + carry_p + foul_p + shot_p
        pass_p, carry_p, foul_p, shot_p = [p / total for p in (pass_p, carry_p, foul_p, shot_p)]

        r = rng.random()
        if r < pass_p:
            start = ball
            end = pass_target(
                rng, start, home=possession == "home", directness=this_team.style.directness
            )
            rng.random()  # receiver choice in simulate_match

            distance_m = ((start.x - end.x) ** 2 + (start.y - end.y) ** 2) ** 0.5
            pressure = _clamp(opp_team.style.press_intensity * rng.uniform(0.2, 1.0), 0.0, 1.0)
            lane_open = _clamp(1.0 - pressure * rng.uniform(0.4, 1.0), 0.0, 1.0)
            difficulty = _clamp((distance_m / 40.0) * (1.0 - lane_open) + pressure * 0.3, 0.0, 1.0)
            risk = this_team.style.pass_risk
            p_complete = 0.90 - 0.25 * difficulty - 0.10 * risk
            p_complete -= squeeze(end, home=possession == "home")
            completed = rng.random() < _clamp(p_complete, 0.45, 0.98)

            if completed:
                ball = end
            else:
                possession = "away" if possession == "home" else "home"
                ball = _turnover_ball(rng, end, team_for(possession).style.counter_attack)
            continue

        if r < pass_p + carry_p:
            start = ball
            end = carry_target(rng, start, home=possession == "home")
            pressure = _clamp(opp_team.style.press_intensity * rng.uniform(0.15, 0.95), 0.0, 1.0)
            if rng.random() < (0.10 + 0.20 * pressure):
                won = rng.random() < _clamp(0.35 + 0.45 * pressure, 0.1, 0.95)
                if won:
                    possession = "away" if possession == "home" else "home"
                    ball = _turnover_ball(rng, end, team_for(possession).style.counter_attack)
                else:
                    ball = end
            else:
                ball = end
            continue

        if r < pass_p + carry_p + foul_p:
            continue

        pos = ball
        xg = _xg_from_position(pos, attacking_left_to_right=(possession == "home"))
        pressure = _clamp(opp_team.style.press_intensity * rng.uniform(0.1, 1.0), 0.0, 1.0)
        xg = _clamp(xg * (1.0 - 0.25 * pressure), 0.02, 0.708)
        is_goal = rng.random() < xg
        if is_goal:
            if possession == "home":
                home_score += 1
            else:
                away_score += 1
            possession = "away" if possession == "home" else "home"
            ball = _sample_ball_start(rng)
        else:
            outcome = rng.choice(["saved", "blocked", "off_target", "woodwork"])
            possession = "away" if possession == "home" else "home"
            _, ball = restart_after_shot(outcome, pos, defending_home=possession == "home")

    return home_score, away_score
