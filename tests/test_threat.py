from __future__ import annotations

import pytest
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.workflow import Director
from playmakers_schema.models import Vec2
from playmakers_stats import StatsEngine
from playmakers_stats.threat import (
    BAND_THRESHOLDS,
    COOLDOWN_MS,
    HORIZON_MS,
    ThreatAnnouncements,
    ThreatTracker,
)
from stats_mcp.server import StatsMcpService


def test_threat_deterministic_prefix_and_goal_reset() -> None:
    events = simulate_match(MatchConfig(seed=382))
    a, b = ThreatTracker(), ThreatTracker()
    for event in events:
        a.ingest(event)
        # Poison future/eval-only fields, and outcome: none may enter features.
        poisoned = event.model_copy(
            update={"labels": ["future-goal"], "ground_truth": {"future": 1}}
        )
        if event.event_type == "shot":
            poisoned = poisoned.model_copy(update={"outcome": "goal"})
        b.ingest(poisoned)
        prefix_ids = {row[1] for row in a.rows}
        for side in ("HOME", "AWAY"):
            team = event.match_id + "_" + side
            prediction = a.predict(team)
            assert prediction == b.predict(team)
            assert set(prediction.evidence.event_ids) <= prefix_ids
        if event.event_type == "goal":
            assert not a.rows
    with pytest.raises(ValueError, match="Historical"):
        a.predict(events[0].match_id + "_HOME", 0)
    with pytest.raises(ValueError, match="ordered"):
        a.ingest(events[-1])


def test_held_out_high_exceeds_low() -> None:
    # Disjoint from fitting seeds; evaluate complete horizons at integer minutes.
    counts = {"High": [0, 0], "Low": [0, 0]}
    for seed in range(2000, 2020):
        events = simulate_match(MatchConfig(seed=seed))
        goals = [e for e in events if e.event_type == "goal"]
        tracker, index = ThreatTracker(), 0
        for minute in range(86):
            now = minute * 60_000
            while index < len(events) and events[index].clock_ms <= now:
                tracker.ingest(events[index])
                index += 1
            for side in ("HOME", "AWAY"):
                team = events[0].match_id + "_" + side
                prediction = tracker.predict(team, now)
                if prediction.level in counts:
                    counts[prediction.level][0] += int(
                        any(
                            g.scoring_team_id == team and now < g.clock_ms <= now + HORIZON_MS
                            for g in goals
                        )
                    )
                    counts[prediction.level][1] += 1
    high, low = counts["High"], counts["Low"]
    assert high[0] / high[1] > low[0] / low[1]


def test_mcp_threat_matches_local_and_hysteresis() -> None:
    events = simulate_match(MatchConfig(seed=382))[:30]
    service, engine = StatsMcpService(), StatsEngine()
    for e in events:
        engine.ingest(e)
        service.ingest_event(e.match_id, e.model_dump(mode="json"))
    e = events[-1]
    team = e.match_id + "_HOME"
    result = engine.goal_threat(team_id=team, match_clock_ms=e.clock_ms)
    assert service.goal_threat(e.match_id, team, e.clock_ms) == result
    assert result.horizon_ms == HORIZON_MS == 120_000
    high = result.model_copy(update={"level": "High", "probability": BAND_THRESHOLDS[1] + 0.01})
    low = result.model_copy(update={"level": "Low", "probability": BAND_THRESHOLDS[0] - 0.01})
    announcements = ThreatAnnouncements()
    assert announcements.update(high, 60_000)
    assert not announcements.update(high, 700_000)
    assert not announcements.update(low, 710_000)
    assert announcements.update(high, 720_000)
    announcements.update(low, 730_000)
    assert not announcements.update(high, 740_000)
    # A blocked entry must not latch High and suppress the next eligible call.
    assert announcements.update(high, 720_000 + COOLDOWN_MS)


@pytest.mark.asyncio
async def test_director_threat_fans_and_analyst_whatif(tmp_path) -> None:
    profiles = [
        ViewerProfile(persona="analyst"),
        *[ViewerProfile(persona="casual", language=lang) for lang in ("en", "es", "fr")],
    ]
    async with Director(
        profiles=profiles, checkpoint_path=str(tmp_path), whatif_rollouts=2
    ) as director:
        cues = []
        for e in simulate_match(MatchConfig(seed=382)):
            cues += await director.on_event(e)
            if e.event_type == "goal":
                break
    assert all(c.goal_threat for c in cues if c.template != "what_if")
    rises = [c for c in cues if c.template == "goal_threat"]
    assert {c.language for c in rises} == {"en", "es", "fr"}
    assert all(c.evidence_event_ids and c.provenance for c in rises)
    whatifs = [c for c in cues if c.template == "what_if"]
    assert whatifs and all(c.persona == "analyst" for c in whatifs)


def test_current_possession_geometry_and_continuous_third_spell() -> None:
    events = simulate_match(MatchConfig(seed=7))
    carry = next(e for e in events if e.event_type == "carry")
    turnover = next(e for e in events if e.event_type == "possession_change")
    home, away = carry.match_id + "_HOME", carry.match_id + "_AWAY"
    tracker = ThreatTracker()
    for sequence, (clock, x) in enumerate(((0, 60), (20_000, 90), (60_000, 94))):
        tracker.ingest(
            carry.model_copy(
                update={
                    "sequence": sequence,
                    "clock_ms": clock,
                    "event_id": f"state:{sequence}",
                    "team_id": home,
                    "end_position": Vec2(x=x, y=34),
                }
            )
        )
    attack = tracker.predict(home)
    assert attack.features["possession"] == 1
    assert attack.features["central_box"] == 1
    assert attack.features["territory"] == pytest.approx(94 / 105)
    assert attack.features["third_spell"] == pytest.approx(40 / 60)
    assert attack.features["third_seconds"] > 0
    assert tracker.predict(away).features["possession"] == 0
    assert tracker.predict(away).features["third_spell"] == 0
    assert attack.features["last_five_territory"] == pytest.approx((60 + 90 + 94) / 315)
    tracker.ingest(
        turnover.model_copy(
            update={
                "sequence": 3,
                "clock_ms": 65_000,
                "event_id": "turnover",
                "team_id": away,
                "to_team_id": away,
                "from_team_id": home,
                "ball_position": Vec2(x=94, y=34),
            }
        )
    )
    assert tracker.predict(home).features["possession"] == 0
    assert tracker.predict(home).features["third_spell"] == 0
    assert tracker.predict(away).features["possession"] == 1
    assert tracker.predict(home).probability < attack.probability


def test_shots_and_failed_passes_wait_for_observed_restart() -> None:
    events = simulate_match(MatchConfig(seed=7))
    for kind in ("shot", "pass"):
        event = next(e for e in events if e.event_type == kind)
        tracker = ThreatTracker()
        event = event.model_copy(update={"completed": False}) if kind == "pass" else event
        tracker.ingest(event)
        for side in ("HOME", "AWAY"):
            features = tracker.predict(event.match_id + "_" + side).features
            assert features["possession"] == 0
            assert features["central_box"] == 0
