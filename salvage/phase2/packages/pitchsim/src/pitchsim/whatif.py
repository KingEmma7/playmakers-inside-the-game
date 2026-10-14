from __future__ import annotations

import random
from dataclasses import dataclass

from pitchsim.config import MatchConfig, TeamStyle
from pitchsim.sim import (
    HALF_MS,
    MATCH_MS,
    PITCH_LENGTH_M,
    PITCH_WIDTH_M,
    Team,
    _advance_ball_after_turnover,
    _apply_story,
    _clamp,
    _expovariate_ms,
    _sample_ball_start,
    _xg_from_position,
)

from gallery_schema.models import (
    CardEvent,
    CarryEvent,
    FoulEvent,
    GoalEvent,
    KickoffEvent,
    MatchEvent,
    PassEvent,
    PeriodEndEvent,
    PeriodStartEvent,
    PossessionChangeEvent,
    ShotEvent,
    SubstitutionEvent,
    TackleEvent,
    Vec2,
)


@dataclass(frozen=True)
class MatchSnapshot:
    match_id: str
    clock_ms: int
    possession: str  # "home" | "away"
    ball: Vec2
    home_score: int
    away_score: int
    home_style: TeamStyle
    away_style: TeamStyle
    story: list


def snapshot_from_events(
    events: list[MatchEvent], *, home_style: TeamStyle, away_style: TeamStyle
) -> MatchSnapshot:
    if not events:
        raise ValueError("Cannot snapshot empty event list.")
    last = events[-1]
    match_id = last.match_id  # type: ignore[attr-defined]

    home_score = 0
    away_score = 0
    possession = "home"
    ball = Vec2(x=52.5, y=34.0)
    story: list = []

    for e in events:
        t = e.event_type  # type: ignore[attr-defined]
        if t == "goal":
            if (e.team_id or "").endswith("_HOME"):
                home_score += 1
            elif (e.team_id or "").endswith("_AWAY"):
                away_score += 1
        if t in ("pass", "carry"):
            ball = getattr(e, "end_position")
            possession = "home" if (e.team_id or "").endswith("_HOME") else "away"
        if t == "shot":
            ball = getattr(e, "position")
            possession = "home" if (e.team_id or "").endswith("_HOME") else "away"
        if t == "possession_change":
            bp = getattr(e, "ball_position")
            ball = bp
            team = getattr(e, "team_id", None)
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
        story=story,
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

    # Event rate calibration: should match sim.py
    base_event_rate_per_s = 0.235

    clock_ms = snapshot.clock_ms
    subs_home = 0
    subs_away = 0

    def current_period(clock_ms: int) -> int:
        return 1 if clock_ms < HALF_MS else 2

    def team_for(pos: str) -> Team:
        return home if pos == "home" else away

    def opp_for(pos: str) -> Team:
        return away if pos == "home" else home

    while clock_ms < MATCH_MS:
        minute = clock_ms // 60000

        this_team = team_for(possession)
        opp_team = opp_for(possession)

        tempo = _clamp(0.5 * (this_team.style.tempo + opp_team.style.tempo), 0.5, 1.6)
        rate = base_event_rate_per_s * tempo
        clock_ms = min(MATCH_MS, clock_ms + max(50, _expovariate_ms(rng, rate)))
        period = current_period(clock_ms)

        # Substitution windows (same heuristic)
        if 60 <= minute <= 85 and rng.random() < 0.03:
            if possession == "home" and subs_home < 3 and this_team.bench_ids:
                subs_home += 1
                continue
            if possession == "away" and subs_away < 3 and this_team.bench_ids:
                subs_away += 1
                continue

        in_attacking_third = (ball.x > 70.0) if possession == "home" else (ball.x < 35.0)
        pass_p = 0.78
        carry_p = 0.13
        foul_p = 0.04 * (1.0 - this_team.style.discipline)
        shot_p = 0.006 + (0.012 if in_attacking_third else 0.0)
        pass_p += 0.06 * (1.0 - this_team.style.directness)
        carry_p += 0.04 * (1.0 - this_team.style.directness)
        shot_p += 0.006 * this_team.style.directness
        total = pass_p + carry_p + foul_p + shot_p
        pass_p, carry_p, foul_p, shot_p = [p / total for p in (pass_p, carry_p, foul_p, shot_p)]

        r = rng.random()
        if r < pass_p:
            start = ball
            base_len = rng.uniform(4.0, 18.0) + (
                this_team.style.directness * rng.uniform(4.0, 18.0)
            )
            forward = rng.uniform(0.2, 1.0) * (0.6 + 0.7 * this_team.style.directness)
            dx = base_len * forward * (1.0 if possession == "home" else -1.0)
            dy = rng.uniform(-10.0, 10.0)
            end = Vec2(
                x=_clamp(start.x + dx, 0.0, PITCH_LENGTH_M),
                y=_clamp(start.y + dy, 0.0, PITCH_WIDTH_M),
            )

            distance_m = ((start.x - end.x) ** 2 + (start.y - end.y) ** 2) ** 0.5
            pressure = _clamp(opp_team.style.press_intensity * rng.uniform(0.2, 1.0), 0.0, 1.0)
            lane_open = _clamp(1.0 - pressure * rng.uniform(0.4, 1.0), 0.0, 1.0)
            difficulty = _clamp((distance_m / 40.0) * (1.0 - lane_open) + pressure * 0.3, 0.0, 1.0)
            risk = this_team.style.pass_risk
            p_complete = 0.90 - 0.25 * difficulty - 0.10 * risk
            completed = rng.random() < _clamp(p_complete, 0.45, 0.98)

            if completed:
                ball = end
            else:
                possession = "away" if possession == "home" else "home"
                ball = _advance_ball_after_turnover(
                    rng, end, team_for(possession).style.counter_attack
                )
            continue

        if r < pass_p + carry_p:
            start = ball
            base = rng.uniform(1.0, 10.0)
            dx = base * (1.0 if possession == "home" else -1.0) * rng.uniform(0.2, 1.0)
            dy = rng.uniform(-6.0, 6.0)
            end = Vec2(
                x=_clamp(start.x + dx, 0.0, PITCH_LENGTH_M),
                y=_clamp(start.y + dy, 0.0, PITCH_WIDTH_M),
            )
            pressure = _clamp(opp_team.style.press_intensity * rng.uniform(0.15, 0.95), 0.0, 1.0)
            if rng.random() < (0.10 + 0.20 * pressure):
                won = rng.random() < _clamp(0.35 + 0.45 * pressure, 0.1, 0.95)
                if won:
                    possession = "away" if possession == "home" else "home"
                    ball = _advance_ball_after_turnover(
                        rng, end, team_for(possession).style.counter_attack
                    )
                else:
                    ball = end
            else:
                ball = end
            continue

        if r < pass_p + carry_p + foul_p:
            continue

        # Shot
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
            ball = _sample_ball_start(rng, possession)

    return home_score, away_score


def win_probability_delta_for_forced_goal(
    snapshot: MatchSnapshot,
    *,
    forced_scoring_team: str,
    rollouts: int = 200,
    seed: int = 0,
) -> dict:
    """
    Compare win probability from a snapshot vs. a counterfactual where the specified team scores +1 now.
    """
    baseline_home_wins = 0
    forced_home_wins = 0

    for i in range(rollouts):
        hs, as_ = rollout_from_snapshot(snapshot, rollout_seed=seed + i)
        if hs > as_:
            baseline_home_wins += 1

    forced = MatchSnapshot(
        **{
            **snapshot.__dict__,
            "home_score": snapshot.home_score + (1 if forced_scoring_team == "home" else 0),
            "away_score": snapshot.away_score + (1 if forced_scoring_team == "away" else 0),
        }
    )
    for i in range(rollouts):
        hs, as_ = rollout_from_snapshot(forced, rollout_seed=seed + 10_000 + i)
        if hs > as_:
            forced_home_wins += 1

    p0 = baseline_home_wins / max(1, rollouts)
    p1 = forced_home_wins / max(1, rollouts)
    return {"home_win_prob_before": p0, "home_win_prob_after": p1, "delta": p1 - p0}
