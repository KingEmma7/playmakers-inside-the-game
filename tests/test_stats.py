from __future__ import annotations

import pytest
from playmakers_schema.models import GoalEvent, PassEvent, ShotEvent, Vec2
from playmakers_stats.engine import StatsEngine


def passing(
    sequence: int = 1,
    *,
    team: str = "TEST_HOME",
    completed: bool = True,
    target: str = "b",
    clock: int = 1000,
) -> PassEvent:
    return PassEvent(
        event_id=f"e{sequence}",
        match_id="test",
        sequence=sequence,
        clock_ms=clock,
        period=1,
        team_id=team,
        from_player_id="a",
        to_player_id=target,
        start_position=Vec2(x=0, y=0),
        end_position=Vec2(x=10, y=0),
        distance_m=10,
        completed=completed,
        pressure=0.4,
        difficulty=0.6,
    )


def shot(sequence: int = 5) -> ShotEvent:
    return ShotEvent(
        event_id=f"e{sequence}",
        match_id="test",
        sequence=sequence,
        clock_ms=2000,
        period=1,
        team_id="TEST_HOME",
        shooter_player_id="a",
        position=Vec2(x=90, y=30),
        xg=0.3,
        outcome="goal",
    )


def test_hand_built_stats() -> None:
    engine = StatsEngine()
    for event in [
        passing(),
        passing(2, team="TEST_AWAY"),
        passing(3, completed=False),
        passing(4, target="c"),
        shot(),
        GoalEvent(
            event_id="e6",
            match_id="test",
            sequence=6,
            clock_ms=2000,
            period=1,
            team_id="TEST_HOME",
            scoring_team_id="TEST_HOME",
            scorer_player_id="a",
            shot_event_id="e5",
        ),
    ]:
        engine.ingest(event)
    possession = engine.possession(match_clock_ms=2000)
    assert possession.home_possession == pytest.approx(2 / 3)
    assert possession.away_possession == pytest.approx(1 / 3)
    assert possession.evidence.event_ids == ["e1", "e2", "e4"]
    pressure = engine.pressure_index(team_id="TEST_HOME", match_clock_ms=2000)
    assert pressure.pressure_index == pytest.approx(0.4)  # Null shot ground_truth is valid.
    assert pressure.evidence.event_ids == ["e1", "e3", "e4"]
    assert engine.pass_difficulty(event_id="e3").difficulty == 0.6
    assert engine.pass_difficulty(event_id="e3").evidence.event_ids == ["e3"]
    assert engine.xg(event_id="e5").xg == 0.3
    assert engine.xg(event_id="e5").evidence.event_ids == ["e5"]
    momentum = engine.momentum(match_clock_ms=2000)
    assert momentum.home_momentum == 1
    assert momentum.away_momentum == -1
    assert momentum.evidence.event_ids == ["e5", "e6"]
    chaos = engine.control_vs_chaos(team_id="TEST_HOME", match_clock_ms=2000)
    assert chaos.pass_network_entropy == 1
    assert chaos.turnover_rate == pytest.approx(1 / 3)
    assert chaos.evidence.event_ids == ["e1", "e3", "e4"]


def test_windows_empty_and_entropy() -> None:
    engine = StatsEngine()
    assert engine.possession(match_clock_ms=0).home_possession == 0.5
    assert engine.momentum(match_clock_ms=0).home_momentum == 0
    engine.ingest(passing())
    engine.ingest(passing(2, clock=5000))
    result = engine.control_vs_chaos(team_id="TEST_HOME", match_clock_ms=5000, window_ms=1000)
    assert result.pass_network_entropy == result.turnover_rate == 0
    assert result.evidence.event_ids == ["e2"]
    assert engine.possession(match_clock_ms=1000).evidence.event_ids == ["e1"]
    assert engine.pressure_index(team_id="unknown", match_clock_ms=5000).evidence.event_ids == []
    assert engine.control_vs_chaos(team_id="unknown", match_clock_ms=0).turnover_rate == 0


@pytest.mark.parametrize("tool", ["pass_difficulty", "xg"])
def test_lookup_errors(tool: str) -> None:
    engine = StatsEngine()
    with pytest.raises(KeyError):
        getattr(engine, tool)(event_id="missing")
    engine.ingest(passing() if tool == "xg" else shot())
    with pytest.raises(ValueError):
        getattr(engine, tool)(event_id="e1" if tool == "xg" else "e5")


def test_ingest_order_and_match_isolation() -> None:
    engine = StatsEngine()
    engine.ingest(passing())
    with pytest.raises(ValueError):
        engine.ingest(passing())
    with pytest.raises(ValueError):
        engine.ingest(passing(2).model_copy(update={"match_id": "another"}))
    with pytest.raises(ValueError):
        engine.possession(match_clock_ms=0, window_ms=-1)


@pytest.mark.parametrize("edges", [3, 6, 7, 10])
def test_uniform_entropy_stays_in_unit_interval(edges: int) -> None:
    engine = StatsEngine()
    for sequence in range(1, edges + 1):
        engine.ingest(passing(sequence, target=f"player{sequence}"))
    result = engine.control_vs_chaos(team_id="TEST_HOME", match_clock_ms=1000)
    assert result.pass_network_entropy == pytest.approx(1)
    assert 0 <= result.pass_network_entropy <= 1


def test_goal_uses_required_scoring_team_without_optional_team_id() -> None:
    engine = StatsEngine()
    engine.ingest(
        GoalEvent(
            event_id="goal",
            match_id="test",
            sequence=0,
            clock_ms=0,
            period=1,
            scoring_team_id="TEST_AWAY",
            scorer_player_id="a",
            shot_event_id="shot",
        )
    )
    result = engine.momentum(match_clock_ms=0)
    assert result.home_momentum == -1
    assert result.evidence.event_ids == ["goal"]
