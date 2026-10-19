"""Team shape and in-play geometry shared by PitchSim and the web pitch.

Coordinates are metres on a 105 x 68 pitch. The home team attacks towards x=105 in both halves.
`web/src/pitchModel.ts` mirrors `BASE_SHAPE` and `slot()`; keep the two in step.
"""

from __future__ import annotations

import math

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


def slot(index: int, ball: Vec2, *, home: bool, attacking: bool) -> Vec2:
    """Where shirt `index + 1` stands when the ball is at `ball` (a formation, not tracking data)."""
    bu, bv = to_team(ball, home)
    base_u, base_v = BASE_SHAPE[index]
    lo, hi = LINE_LIMITS[index]
    if index == 0:
        u = base_u + max(0.0, bu - 30.0) * 0.12
        v = 34.0 + (bv - 34.0) * 0.2
    else:
        u = base_u + (bu - 40.0) * 0.72 + (6.0 if attacking else -2.0)
        v = 34.0 + (base_v - 34.0) * 0.85 + (bv - 34.0) * 0.3
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
        return "keeper_save", from_team(4.0, 34.0, defending_home)
    if outcome == "blocked":
        u, v = to_team(position, defending_home)
        return "shot_blocked", from_team(_clamp(u + 6.0, 6.0, 40.0), v, defending_home)
    return "goal_kick", from_team(5.5, 34.0 + (4.0 if position.y > 34.0 else -4.0), defending_home)
