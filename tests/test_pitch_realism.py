from __future__ import annotations

import pytest
from pitchsim.config import MatchConfig
from pitchsim.shape import ATTACK_LIMIT_M, BASE_SHAPE, keep_in_play, slot
from pitchsim.sim import simulate_match
from playmakers_schema.models import Vec2

SEEDS = (1, 7, 42)


def _ball_points(event: object) -> list[Vec2]:
    return [
        getattr(event, key)
        for key in ("start_position", "end_position", "position", "ball_position")
        if hasattr(event, key)
    ]


@pytest.mark.parametrize("seed", SEEDS)
def test_ball_stays_in_play_and_off_the_lines(seed: int) -> None:
    for event in simulate_match(MatchConfig(seed=seed)):
        for p in _ball_points(event):
            assert 1.0 <= p.x <= 104.0 and 1.0 <= p.y <= 67.0, (event.event_id, p)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_player_on_the_ball_is_the_one_who_plays_it(seed: int) -> None:
    holder: str | None = None
    for event in simulate_match(MatchConfig(seed=seed)):
        actor = {
            "pass": getattr(event, "from_player_id", None),
            "carry": event.player_id,
            "shot": getattr(event, "shooter_player_id", None),
        }.get(event.event_type)
        if actor and holder:
            assert actor == holder, event.event_id
        if event.event_type == "pass":
            holder = event.to_player_id if event.completed else None
        elif event.event_type in ("carry", "possession_change"):
            holder = event.player_id
        elif event.event_type == "kickoff":
            holder = None


@pytest.mark.parametrize("seed", SEEDS)
def test_every_shot_that_misses_hands_the_ball_to_the_defending_team(seed: int) -> None:
    events = simulate_match(MatchConfig(seed=seed))
    for i, event in enumerate(events):
        if event.event_type == "shot" and event.outcome != "goal":
            nxt = events[i + 1]
            assert nxt.event_type == "possession_change"
            assert nxt.from_team_id == event.team_id
            assert nxt.reason in {"keeper_save", "goal_kick", "shot_blocked"}


def test_substitute_takes_the_replaced_players_place() -> None:
    events = simulate_match(MatchConfig(seed=7))
    for i, event in enumerate(events):
        if event.event_type != "substitution":
            continue
        later = {e.player_id for e in events[i + 1 :] if e.player_id}
        assert event.player_out_id not in later
    assert any(e.player_id and e.player_id[-2:] > "11" for e in events)


def test_deep_balls_are_cut_back_not_pinned_to_the_goal_line() -> None:
    end = keep_in_play(Vec2(x=95.0, y=34.0), 20.0, 0.0, home=True)
    assert end.x < ATTACK_LIMIT_M
    end = keep_in_play(Vec2(x=10.0, y=34.0), -20.0, 0.0, home=False)
    assert end.x > 105.0 - ATTACK_LIMIT_M
    wide = keep_in_play(Vec2(x=50.0, y=64.0), 0.0, 10.0, home=True)
    assert wide.y < 66.0


def test_formation_slots_are_inside_the_pitch_for_any_ball_position() -> None:
    for bx in range(0, 106, 5):
        for by in range(0, 69, 4):
            ball = Vec2(x=bx, y=by)
            for home in (True, False):
                for attacking in (True, False):
                    for i in range(len(BASE_SHAPE)):
                        s = slot(i, ball, home=home, attacking=attacking)
                        assert 0.0 <= s.x <= 105.0 and 3.0 <= s.y <= 65.0
