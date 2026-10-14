from __future__ import annotations

import math
import random
from dataclasses import dataclass

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

from pitchsim.config import MatchConfig, StoryEvent, TeamStyle

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0
MATCH_MS = 90 * 60 * 1000
HALF_MS = 45 * 60 * 1000


@dataclass(frozen=True)
class Team:
    team_id: str
    name: str
    style: TeamStyle
    player_ids: list[str]
    bench_ids: list[str]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _dist(a: Vec2, b: Vec2) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _expovariate_ms(rng: random.Random, rate_per_s: float) -> int:
    # rate_per_s > 0. Larger => shorter deltas.
    u = max(1e-12, rng.random())
    dt_s = -math.log(u) / rate_per_s
    return int(dt_s * 1000)


def _xg_from_position(pos: Vec2, attacking_left_to_right: bool) -> float:
    goal_x = PITCH_LENGTH_M if attacking_left_to_right else 0.0
    dx = abs(goal_x - pos.x)
    dy = abs((PITCH_WIDTH_M / 2.0) - pos.y)
    dist = math.hypot(dx, dy)
    # A simple smooth curve: close-range ~0.64, 18m ~0.24, 30m ~0.11
    xg = 0.688 * math.exp(-dist / 17.5)
    return _clamp(xg, 0.02, 0.708)


def _sample_ball_start(rng: random.Random, possession: str) -> Vec2:
    # Start centrally, small jitter.
    return Vec2(
        x=52.5 + rng.uniform(-1.0, 1.0),
        y=34.0 + rng.uniform(-1.0, 1.0),
    )


def _advance_ball_after_turnover(rng: random.Random, ball: Vec2, counter_attack: float) -> Vec2:
    # Quick transition: slightly more vertical progress.
    dx = rng.uniform(-12.0, 12.0) + (counter_attack * rng.uniform(-6.0, 6.0))
    dy = rng.uniform(-10.0, 10.0)
    return Vec2(
        x=_clamp(ball.x + dx, 0.0, PITCH_LENGTH_M), y=_clamp(ball.y + dy, 0.0, PITCH_WIDTH_M)
    )


def _apply_story(style: TeamStyle, story_event: StoryEvent) -> tuple[TeamStyle, list[str]]:
    labels: list[str] = []
    label = story_event.label or story_event.type
    labels.append(label)

    if story_event.type == "press_collapse":
        # Reduce press and increase pass risk.
        new_style = style.model_copy(
            update={
                "press_intensity": _clamp(style.press_intensity * 0.55, 0.0, 1.0),
                "pass_risk": _clamp(style.pass_risk * 1.25, 0.0, 1.0),
            }
        )
        return new_style, labels

    if story_event.type == "goal_boost":
        new_style = style.model_copy(update={"tempo": _clamp(style.tempo * 1.10, 0.5, 1.6)})
        return new_style, labels

    if story_event.type == "red_card":
        # Lower tempo, lower press.
        new_style = style.model_copy(
            update={
                "tempo": _clamp(style.tempo * 0.92, 0.5, 1.6),
                "press_intensity": _clamp(style.press_intensity * 0.75, 0.0, 1.0),
            }
        )
        return new_style, labels

    # Exhaustive for v1
    raise AssertionError(f"Unhandled story event type: {story_event.type}")


def simulate_match(config: MatchConfig) -> list[MatchEvent]:
    rng = random.Random(config.seed)
    match_id = f"match_{config.seed}"

    home = Team(
        team_id=f"{match_id}_HOME",
        name="Northbridge Rovers",
        style=config.home_style,
        player_ids=[f"{match_id}_H{idx:02d}" for idx in range(1, 12)],
        bench_ids=[f"{match_id}_H{idx:02d}" for idx in range(12, 19)],
    )
    away = Team(
        team_id=f"{match_id}_AWAY",
        name="Southport Athletic",
        style=config.away_style,
        player_ids=[f"{match_id}_A{idx:02d}" for idx in range(1, 12)],
        bench_ids=[f"{match_id}_A{idx:02d}" for idx in range(12, 19)],
    )

    possession = "home" if rng.random() < 0.5 else "away"
    ball = _sample_ball_start(rng, possession)

    home_score = 0
    away_score = 0

    story_queue = sorted(config.story, key=lambda s: s.minute)
    next_story_idx = 0
    active_story_labels: list[str] = []
    pending_style_changes: list[StoryEvent] = []

    # Event rate calibration: tuned to land near ~900-1100 passes with default styles.
    base_event_rate_per_s = 0.235

    seq = 0
    events: list[MatchEvent] = []

    def add(ev: MatchEvent) -> None:
        nonlocal seq
        if pending_style_changes:
            ev = ev.model_copy(
                update={
                    "ground_truth": {
                        **(ev.ground_truth or {}),
                        "style_changes": [change.model_dump() for change in pending_style_changes],
                    }
                }
            )
            pending_style_changes.clear()
        events.append(ev)
        seq += 1

    def ev_id() -> str:
        return f"{match_id}:{seq:06d}"

    def current_period(clock_ms: int) -> int:
        return 1 if clock_ms < HALF_MS else 2

    def team_for(pos: str) -> Team:
        return home if pos == "home" else away

    def opp_for(pos: str) -> Team:
        return away if pos == "home" else home

    add(
        PeriodStartEvent(
            event_id=ev_id(),
            match_id=match_id,
            sequence=seq,
            clock_ms=0,
            period=1,
            labels=[],
            ground_truth=None,
        )
    )
    add(
        KickoffEvent(
            event_id=ev_id(),
            match_id=match_id,
            sequence=seq,
            clock_ms=0,
            period=1,
            team_id=team_for(possession).team_id,
            player_id=None,
            start_position=ball,
            labels=[],
            ground_truth=None,
        )
    )

    clock_ms = 0
    subs_home = 0
    subs_away = 0

    while clock_ms < MATCH_MS:
        # Half-time markers.
        if clock_ms < HALF_MS and (clock_ms + 1) >= HALF_MS:
            add(
                PeriodEndEvent(
                    event_id=ev_id(),
                    match_id=match_id,
                    sequence=seq,
                    clock_ms=HALF_MS,
                    period=1,
                    labels=[],
                    ground_truth=None,
                )
            )
            add(
                PeriodStartEvent(
                    event_id=ev_id(),
                    match_id=match_id,
                    sequence=seq,
                    clock_ms=HALF_MS,
                    period=2,
                    labels=[],
                    ground_truth=None,
                )
            )
            # Kickoff for second half.
            possession = "home" if rng.random() < 0.5 else "away"
            ball = _sample_ball_start(rng, possession)
            add(
                KickoffEvent(
                    event_id=ev_id(),
                    match_id=match_id,
                    sequence=seq,
                    clock_ms=HALF_MS,
                    period=2,
                    team_id=team_for(possession).team_id,
                    player_id=None,
                    start_position=ball,
                    labels=[],
                    ground_truth=None,
                )
            )

        # Apply story events at minute boundaries.
        minute = clock_ms // 60000
        while next_story_idx < len(story_queue) and story_queue[next_story_idx].minute <= minute:
            se = story_queue[next_story_idx]
            pending_style_changes.append(se)
            next_story_idx += 1
            if se.team == "home":
                updated, labels = _apply_story(home.style, se)
                home = Team(**{**home.__dict__, "style": updated})
                active_story_labels.extend(labels)
            else:
                updated, labels = _apply_story(away.style, se)
                away = Team(**{**away.__dict__, "style": updated})
                active_story_labels.extend(labels)

        this_team = team_for(possession)
        opp_team = opp_for(possession)

        # Global event cadence depends on both teams' tempo.
        tempo = _clamp(0.5 * (this_team.style.tempo + opp_team.style.tempo), 0.5, 1.6)
        rate = base_event_rate_per_s * tempo
        clock_ms = min(MATCH_MS, clock_ms + max(50, _expovariate_ms(rng, rate)))
        period = current_period(clock_ms)

        # Substitution windows (simple heuristic).
        if 60 <= minute <= 85 and rng.random() < 0.03:
            if possession == "home" and subs_home < 3 and this_team.bench_ids:
                out_id = rng.choice(this_team.player_ids)
                in_id = this_team.bench_ids[subs_home]
                subs_home += 1
                add(
                    SubstitutionEvent(
                        event_id=ev_id(),
                        match_id=match_id,
                        sequence=seq,
                        clock_ms=clock_ms,
                        period=period,
                        team_id=this_team.team_id,
                        player_out_id=out_id,
                        player_in_id=in_id,
                        reason="fresh_legs",
                        labels=list(active_story_labels),
                        ground_truth=None,
                    )
                )
                continue
            if possession == "away" and subs_away < 3 and this_team.bench_ids:
                out_id = rng.choice(this_team.player_ids)
                in_id = this_team.bench_ids[subs_away]
                subs_away += 1
                add(
                    SubstitutionEvent(
                        event_id=ev_id(),
                        match_id=match_id,
                        sequence=seq,
                        clock_ms=clock_ms,
                        period=period,
                        team_id=this_team.team_id,
                        player_out_id=out_id,
                        player_in_id=in_id,
                        reason="fresh_legs",
                        labels=list(active_story_labels),
                        ground_truth=None,
                    )
                )
                continue

        # Decide event type.
        # Pass dominates; carry is occasional; shot depends on position; foul rare.
        in_attacking_third = (ball.x > 70.0) if possession == "home" else (ball.x < 35.0)
        pass_p = 0.78
        carry_p = 0.13
        foul_p = 0.04 * (1.0 - this_team.style.discipline)
        # Shots are rare relative to passes; increase only when in attacking third.
        shot_p = 0.006 + (0.012 if in_attacking_third else 0.0)

        # Style adjustments.
        pass_p += 0.06 * (1.0 - this_team.style.directness)
        carry_p += 0.04 * (1.0 - this_team.style.directness)
        shot_p += 0.006 * this_team.style.directness

        # Normalize.
        total = pass_p + carry_p + foul_p + shot_p
        pass_p, carry_p, foul_p, shot_p = [p / total for p in (pass_p, carry_p, foul_p, shot_p)]

        r = rng.random()
        if r < pass_p:
            passer = rng.choice(this_team.player_ids)
            receiver = rng.choice([p for p in this_team.player_ids if p != passer])
            start = ball

            # Pass length depends on directness.
            base_len = rng.uniform(4.0, 18.0) + (
                this_team.style.directness * rng.uniform(4.0, 18.0)
            )
            # Forwardness bias.
            forward = rng.uniform(0.2, 1.0) * (0.6 + 0.7 * this_team.style.directness)
            dx = base_len * forward * (1.0 if possession == "home" else -1.0)
            dy = rng.uniform(-10.0, 10.0)
            end = Vec2(
                x=_clamp(start.x + dx, 0.0, PITCH_LENGTH_M),
                y=_clamp(start.y + dy, 0.0, PITCH_WIDTH_M),
            )

            distance_m = _dist(start, end)
            pressure = _clamp(opp_team.style.press_intensity * rng.uniform(0.2, 1.0), 0.0, 1.0)
            lane_open = _clamp(1.0 - pressure * rng.uniform(0.4, 1.0), 0.0, 1.0)
            difficulty = _clamp((distance_m / 40.0) * (1.0 - lane_open) + pressure * 0.3, 0.0, 1.0)

            # Completion probability.
            risk = this_team.style.pass_risk
            p_complete = 0.90 - 0.25 * difficulty - 0.10 * risk
            completed = rng.random() < _clamp(p_complete, 0.45, 0.98)

            add(
                PassEvent(
                    event_id=ev_id(),
                    match_id=match_id,
                    sequence=seq,
                    clock_ms=clock_ms,
                    period=period,
                    team_id=this_team.team_id,
                    player_id=passer,
                    from_player_id=passer,
                    to_player_id=receiver,
                    start_position=start,
                    end_position=end,
                    distance_m=distance_m,
                    completed=completed,
                    pressure=pressure,
                    difficulty=difficulty,
                    labels=list(active_story_labels),
                    ground_truth={"lane_open": lane_open},
                )
            )

            if completed:
                ball = end
            else:
                old_team = this_team.team_id
                possession = "away" if possession == "home" else "home"
                ball = _advance_ball_after_turnover(
                    rng, end, team_for(possession).style.counter_attack
                )
                add(
                    PossessionChangeEvent(
                        event_id=ev_id(),
                        match_id=match_id,
                        sequence=seq,
                        clock_ms=clock_ms,
                        period=period,
                        team_id=team_for(possession).team_id,
                        player_id=None,
                        from_team_id=old_team,
                        to_team_id=team_for(possession).team_id,
                        reason="pass_incomplete",
                        ball_position=ball,
                        labels=list(active_story_labels),
                        ground_truth=None,
                    )
                )

            continue

        if r < pass_p + carry_p:
            carrier = rng.choice(this_team.player_ids)
            start = ball
            # Carry length and direction.
            base = rng.uniform(1.0, 10.0)
            dx = base * (1.0 if possession == "home" else -1.0) * rng.uniform(0.2, 1.0)
            dy = rng.uniform(-6.0, 6.0)
            end = Vec2(
                x=_clamp(start.x + dx, 0.0, PITCH_LENGTH_M),
                y=_clamp(start.y + dy, 0.0, PITCH_WIDTH_M),
            )
            distance_m = _dist(start, end)
            pressure = _clamp(opp_team.style.press_intensity * rng.uniform(0.15, 0.95), 0.0, 1.0)
            add(
                CarryEvent(
                    event_id=ev_id(),
                    match_id=match_id,
                    sequence=seq,
                    clock_ms=clock_ms,
                    period=period,
                    team_id=this_team.team_id,
                    player_id=carrier,
                    start_position=start,
                    end_position=end,
                    distance_m=distance_m,
                    pressure=pressure,
                    labels=list(active_story_labels),
                    ground_truth=None,
                )
            )

            # Chance of tackle/turnover under pressure.
            if rng.random() < (0.10 + 0.20 * pressure):
                tackler = rng.choice(opp_team.player_ids)
                won = rng.random() < _clamp(0.35 + 0.45 * pressure, 0.1, 0.95)
                add(
                    TackleEvent(
                        event_id=ev_id(),
                        match_id=match_id,
                        sequence=seq,
                        clock_ms=clock_ms,
                        period=period,
                        team_id=opp_team.team_id,
                        player_id=tackler,
                        tackler_player_id=tackler,
                        target_player_id=carrier,
                        position=end,
                        won_ball=won,
                        labels=list(active_story_labels),
                        ground_truth=None,
                    )
                )
                if won:
                    old_team = this_team.team_id
                    possession = "away" if possession == "home" else "home"
                    ball = _advance_ball_after_turnover(
                        rng, end, team_for(possession).style.counter_attack
                    )
                    add(
                        PossessionChangeEvent(
                            event_id=ev_id(),
                            match_id=match_id,
                            sequence=seq,
                            clock_ms=clock_ms,
                            period=period,
                            team_id=team_for(possession).team_id,
                            player_id=None,
                            from_team_id=old_team,
                            to_team_id=team_for(possession).team_id,
                            reason="tackle_won",
                            ball_position=ball,
                            labels=list(active_story_labels),
                            ground_truth=None,
                        )
                    )
                else:
                    ball = end
            else:
                ball = end
            continue

        if r < pass_p + carry_p + foul_p:
            fouler = rng.choice(opp_team.player_ids)
            fouled = rng.choice(this_team.player_ids)
            position = ball

            # Card probability.
            yellow_p = 0.10 * (1.0 - this_team.style.discipline)
            red_p = 0.015 * (1.0 - this_team.style.discipline)
            card_awarded: str = "none"
            if rng.random() < red_p:
                card_awarded = "red"
            elif rng.random() < yellow_p:
                card_awarded = "yellow"

            add(
                FoulEvent(
                    event_id=ev_id(),
                    match_id=match_id,
                    sequence=seq,
                    clock_ms=clock_ms,
                    period=period,
                    team_id=opp_team.team_id,
                    player_id=fouler,
                    fouler_player_id=fouler,
                    fouled_player_id=fouled,
                    position=position,
                    card_awarded=card_awarded,  # type: ignore[arg-type]
                    labels=list(active_story_labels),
                    ground_truth=None,
                )
            )

            if card_awarded in ("yellow", "red"):
                add(
                    CardEvent(
                        event_id=ev_id(),
                        match_id=match_id,
                        sequence=seq,
                        clock_ms=clock_ms,
                        period=period,
                        team_id=opp_team.team_id,
                        player_id=fouler,
                        carded_player_id=fouler,
                        color=card_awarded,  # type: ignore[arg-type]
                        reason="reckless_challenge",
                        labels=list(active_story_labels),
                        ground_truth=None,
                    )
                )

                # If red, flip story-style impact for the offending team.
                if card_awarded == "red":
                    se = StoryEvent(
                        minute=minute,
                        type="red_card",
                        team=("home" if possession == "away" else "away"),
                    )
                    if se.team == "home":
                        updated, labels = _apply_story(home.style, se)
                        home = Team(**{**home.__dict__, "style": updated})
                        active_story_labels.extend(labels)
                    else:
                        updated, labels = _apply_story(away.style, se)
                        away = Team(**{**away.__dict__, "style": updated})
                        active_story_labels.extend(labels)

            # After foul, possession typically remains with fouled team.
            continue

        # Shot
        shooter = rng.choice(this_team.player_ids)
        pos = ball
        xg = _xg_from_position(pos, attacking_left_to_right=(possession == "home"))

        # Reduce xG slightly under pressure.
        pressure = _clamp(opp_team.style.press_intensity * rng.uniform(0.1, 1.0), 0.0, 1.0)
        xg = _clamp(xg * (1.0 - 0.25 * pressure), 0.02, 0.708)

        is_goal = rng.random() < xg
        outcome = "goal" if is_goal else rng.choice(["saved", "blocked", "off_target", "woodwork"])

        shot_event_id = ev_id()
        add(
            ShotEvent(
                event_id=shot_event_id,
                match_id=match_id,
                sequence=seq,
                clock_ms=clock_ms,
                period=period,
                team_id=this_team.team_id,
                player_id=shooter,
                shooter_player_id=shooter,
                position=pos,
                xg=xg,
                outcome=outcome,  # type: ignore[arg-type]
                shot_speed_kmh=60.0 + rng.uniform(0.0, 55.0),
                labels=list(active_story_labels) + (["key_moment"] if is_goal else []),
                ground_truth={"pressure": pressure},
            )
        )

        if is_goal:
            if possession == "home":
                home_score += 1
            else:
                away_score += 1
            add(
                GoalEvent(
                    event_id=ev_id(),
                    match_id=match_id,
                    sequence=seq,
                    clock_ms=clock_ms,
                    period=period,
                    team_id=this_team.team_id,
                    player_id=shooter,
                    scoring_team_id=this_team.team_id,
                    scorer_player_id=shooter,
                    assist_player_id=None,
                    shot_event_id=shot_event_id,
                    labels=list(active_story_labels) + ["key_moment"],
                    ground_truth={"score": {"home": home_score, "away": away_score}},
                )
            )
            # Possession resets for kickoff.
            old_team = this_team.team_id
            possession = "away" if possession == "home" else "home"
            ball = _sample_ball_start(rng, possession)
            add(
                PossessionChangeEvent(
                    event_id=ev_id(),
                    match_id=match_id,
                    sequence=seq,
                    clock_ms=clock_ms,
                    period=period,
                    team_id=team_for(possession).team_id,
                    player_id=None,
                    from_team_id=old_team,
                    to_team_id=team_for(possession).team_id,
                    reason="goal_kickoff",
                    ball_position=ball,
                    labels=list(active_story_labels),
                    ground_truth=None,
                )
            )

    # Full-time marker.
    add(
        PeriodEndEvent(
            event_id=ev_id(),
            match_id=match_id,
            sequence=seq,
            clock_ms=MATCH_MS,
            period=2,
            labels=[],
            ground_truth={"final_score": {"home": home_score, "away": away_score}},
        )
    )

    return events
