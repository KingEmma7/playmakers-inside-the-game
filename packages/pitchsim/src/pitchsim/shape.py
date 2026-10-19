"""Team shape and in-play geometry shared by PitchSim and the web pitch.

Coordinates are metres on a 105 x 68 pitch. The home team attacks towards x=105 in both halves.
`web/src/pitchModel.ts` mirrors `BASE_SHAPE` and `slot()`; keep the two in step.
"""

from __future__ import annotations

import math
import random

from playmakers_schema.models import Vec2

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0

# 4-3-3 in team-relative metres: u runs from the team's own goal line (0) to the opponent's (105),
# v runs across the pitch. Index 0 is shirt 1 (goalkeeper), index 10 is shirt 11.
BASE_SHAPE: tuple[tuple[float, float], ...] = (
    (5.0, 34.0),
    (24.0, 8.0),
    (21.0, 26.0),
    (21.0, 42.0),
    (24.0, 60.0),
    (36.0, 20.0),
    (33.0, 34.0),
    (36.0, 48.0),
    (47.0, 12.0),
    (50.0, 34.0),
    (47.0, 56.0),
)
# How far forward each line may push (u), by shirt index.
LINE_LIMITS: tuple[tuple[float, float], ...] = (
    (2.0, 18.0),
    *[(5.0, 72.0)] * 4,
    *[(9.0, 88.0)] * 3,
    *[(20.0, 98.0)] * 3,
)
ATTACK_LIMIT_M = 99.0
OWN_LIMIT_M = 6.0
SIDE_MARGIN_M = 2.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def to_team(ball: Vec2, home: bool) -> tuple[float, float]:
    return (ball.x, ball.y) if home else (PITCH_LENGTH_M - ball.x, PITCH_WIDTH_M - ball.y)


def from_team(u: float, v: float, home: bool) -> Vec2:
    x, y = (u, v) if home else (PITCH_LENGTH_M - u, PITCH_WIDTH_M - v)
    return Vec2(x=_clamp(x, 0.0, PITCH_LENGTH_M), y=_clamp(y, 0.0, PITCH_WIDTH_M))


# Team shape constants, fitted to open tracking data (Metrica Sports sample games; see
# pitchsim/reference/metrica_derived.json): outfield width ~42 m in possession and ~37 m out of it,
# depth ~30-33 m, the keeper ~4 m off the line and on the ball-to-goal line.
SHAPE_CENTRE_U = 33.0
LINE_SHIFT = 0.72
IN_POSSESSION_PUSH = 6.0
OUT_OF_POSSESSION_PUSH = 7.0
WIDTH_IN_MIN = 0.55
WIDTH_IN_GAIN = 0.4
WIDTH_OUT_MIN = 0.6
WIDTH_OUT_GAIN = 0.18
BALL_SHIFT_IN = 0.3
BALL_SHIFT_OUT = 0.42
DEPTH_IN_GAIN = 0.25
DEPTH_OUT_MIN = 0.85
DEPTH_OUT_GAIN = 0.3
KEEPER_ANGLE = 0.6
PASS_LENGTH_SCALE = 0.95
PASS_LATERAL_M = 19.0


def keeper_depth(bu: float) -> float:
    """Metres off the goal line: close in when the ball is near, sweeping up when it is far."""
    return _clamp(1.5 + 0.1 * bu if bu < 35.0 else 5.0 + (bu - 35.0) * 0.12, 1.5, 13.0)


def slot(index: int, ball: Vec2, *, home: bool, attacking: bool) -> Vec2:
    """Where shirt `index + 1` stands when the ball is at `ball` (a formation, not tracking data).

    In possession the team stretches (wide players hold the touchline, the back line steps up);
    out of possession it is compact and shifts across to the ball side. The keeper stands on the
    line from the ball to the centre of the goal."""
    bu, bv = to_team(ball, home)
    base_u, base_v = BASE_SHAPE[index]
    lo, hi = LINE_LIMITS[index]
    if index == 0:
        u = keeper_depth(bu)
        v = 34.0 + _clamp(KEEPER_ANGLE * (bv - 34.0) * u / max(bu, u + 1.0), -5.0, 5.0)
        return from_team(u, v, home)
    if attacking:
        depth = 1.0 + DEPTH_IN_GAIN * _clamp((bu - 35.0) / 50.0, 0.0, 1.0)
        width = WIDTH_IN_MIN + WIDTH_IN_GAIN * _clamp(bu / 85.0, 0.0, 1.0)
        shift, push = BALL_SHIFT_IN, IN_POSSESSION_PUSH
    else:
        depth = DEPTH_OUT_MIN + DEPTH_OUT_GAIN * _clamp(bu / 70.0, 0.0, 1.0)
        width = WIDTH_OUT_MIN + WIDTH_OUT_GAIN * _clamp(bu / 80.0, 0.0, 1.0)
        shift, push = BALL_SHIFT_OUT, OUT_OF_POSSESSION_PUSH
    u = SHAPE_CENTRE_U + (base_u - SHAPE_CENTRE_U) * depth + (bu - 40.0) * LINE_SHIFT + push
    v = 34.0 + (base_v - 34.0) * width + (bv - 34.0) * shift
    return from_team(_clamp(u, lo, hi), _clamp(v, 3.0, PITCH_WIDTH_M - 3.0), home)


def nearest(
    ball: Vec2, point: Vec2, *, home: bool, attacking: bool, exclude: set[int] | None = None
) -> list[int]:
    """Shirt indexes ordered by how close their formation slot is to `point`."""
    skip = exclude or set()
    order = [i for i in range(len(BASE_SHAPE)) if i not in skip]
    return sorted(
        order,
        key=lambda i: math.dist(
            (point.x, point.y),
            (
                (s := slot(i, ball, home=home, attacking=attacking)).x,
                s.y,
            ),
        ),
    )


THIRD_SHOT_P = 0.008
BOX_SHOT_P = 0.07
CENTRAL_SHOT_P = 0.6


def shot_bonus(ball: Vec2, *, home: bool) -> float:
    """Extra per-event shot probability: a little in the final third, most in the central box."""
    u, v = to_team(ball, home)
    in_box = u > PITCH_LENGTH_M - 16.5 and abs(v - PITCH_WIDTH_M / 2.0) < 20.16
    central = in_box and abs(v - PITCH_WIDTH_M / 2.0) < 11.0
    return (
        (THIRD_SHOT_P if u > 70.0 else 0.0)
        + (BOX_SHOT_P if in_box else 0.0)
        + (CENTRAL_SHOT_P if central else 0.0)
    )


def recycle(ball: Vec2, *, home: bool) -> float:
    """Pull on the forward share of a pass near the opponent's box, so attacks circulate."""
    u, _ = to_team(ball, home)
    return 0.9 * max(0.0, u - 62.0) / 37.0


def keep_in_play(start: Vec2, dx: float, dy: float, *, home: bool) -> Vec2:
    """Move the ball by (dx, dy) but keep it in play: deep balls are cut back, wide ones folded in."""
    u, v = to_team(start, home)
    du, dv = (dx, dy) if home else (-dx, -dy)
    u, v = u + du, v + dv
    if u > ATTACK_LIMIT_M:
        u = ATTACK_LIMIT_M - (u - ATTACK_LIMIT_M) * 0.6
    if u < OWN_LIMIT_M:
        u = OWN_LIMIT_M + (OWN_LIMIT_M - u) * 0.6
    if v < SIDE_MARGIN_M:
        v = SIDE_MARGIN_M + (SIDE_MARGIN_M - v) * 0.6
    if v > PITCH_WIDTH_M - SIDE_MARGIN_M:
        v = PITCH_WIDTH_M - SIDE_MARGIN_M - (v - (PITCH_WIDTH_M - SIDE_MARGIN_M)) * 0.6
    u = _clamp(u, 1.0, PITCH_LENGTH_M - 1.0)
    v = _clamp(v, 1.0, PITCH_WIDTH_M - 1.0)
    return from_team(u, v, home)


def restart_after_shot(outcome: str, position: Vec2, *, defending_home: bool) -> tuple[str, Vec2]:
    """Possession change after a shot that did not score: keeper save, goal kick or blocked shot."""
    if outcome == "saved":
        # The keeper holds it where the save was made: on the line from the shot to the goal.
        _, v = to_team(position, defending_home)
        return "keeper_save", from_team(3.0, 34.0 + _clamp((v - 34.0) * 0.12, -3.0, 3.0), defending_home)
    if outcome == "blocked":
        u, v = to_team(position, defending_home)
        return "shot_blocked", from_team(_clamp(u + 6.0, 6.0, 40.0), v, defending_home)
    return "goal_kick", from_team(5.5, 34.0 + (4.0 if position.y > 34.0 else -4.0), defending_home)


BUILD_UP_PUSH = 0.6
RESET_P = 0.05
SWITCH_P = 0.14
SWITCH_WIDE_M = 9.0
SWITCH_MAX_U = 75.0
SQUEEZE_U = 75.0
SQUEEZE = 0.03
CENTRE_PULL = 0.0


def pass_target(rng: random.Random, start: Vec2, *, home: bool, directness: float) -> Vec2:
    """Where a pass from `start` is aimed: build-up out of the back, recycling near the box,
    resets to the back line when an attack is held up, and switches of play to the far side."""
    u, v = to_team(start, home)
    base_len = PASS_LENGTH_SCALE * (rng.uniform(4.0, 18.0) + directness * rng.uniform(4.0, 18.0))
    forward = rng.uniform(0.2, 1.0) * (0.6 + 0.7 * directness)
    forward -= recycle(start, home=home)
    forward += BUILD_UP_PUSH * max(0.0, 40.0 - u) / 34.0
    du = base_len * forward
    dv = rng.uniform(-PASS_LATERAL_M, PASS_LATERAL_M) + CENTRE_PULL * (PITCH_WIDTH_M / 2.0 - v)
    if (
        u < SWITCH_MAX_U
        and abs(v - PITCH_WIDTH_M / 2.0) > SWITCH_WIDE_M
        and rng.random() < SWITCH_P
    ):
        # Switch of play: a long diagonal to the far side, the wide player there holding width.
        far = PITCH_WIDTH_M - v + rng.uniform(-6.0, 6.0)
        dv = _clamp(far, 6.0, PITCH_WIDTH_M - 6.0) - v
        du = rng.uniform(-4.0, 14.0)
    elif u > 70.0 and rng.random() < RESET_P:
        # Reset: the attack is held up, so the ball goes back to the midfield or the back line.
        du = -rng.uniform(14.0, 30.0)
    return keep_in_play(start, du if home else -du, dv if home else -dv, home=home)


def carry_target(rng: random.Random, start: Vec2, *, home: bool) -> Vec2:
    """Where a carry from `start` ends: forward, less so near the box, drifting inside off a wing."""
    u, v = to_team(start, home)
    base = rng.uniform(1.0, 10.0)
    push = rng.uniform(0.2, 1.0) - 0.8 * recycle(start, home=home)
    du = base * push
    dv = rng.uniform(-6.0, 6.0) + 0.0 * (PITCH_WIDTH_M / 2.0 - v)
    return keep_in_play(start, du if home else -du, dv if home else -dv, home=home)


def squeeze(end: Vec2, *, home: bool) -> float:
    """Lower completion for passes into a packed final third, so long spells there end."""
    u, _ = to_team(end, home)
    return SQUEEZE if u > SQUEEZE_U else 0.0
