from __future__ import annotations

import pytest
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_agents.contracts import ViewerProfile
from playmakers_agents.workflow import Director
from playmakers_stats import StatsEngine
from playmakers_stats.threat import BAND_THRESHOLDS, ThreatAnnouncements, ThreatTracker
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
        for side in ("HOME", "AWAY"):
            team = event.match_id + "_" + side
            assert a.predict(team) == b.predict(team)
            assert all(
                eid in {row[1] for row in a.rows} for eid in a.predict(team).evidence.event_ids
            )
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
                            g.scoring_team_id == team and now < g.clock_ms <= now + 300_000
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
    high = result.model_copy(update={"level": "High", "probability": BAND_THRESHOLDS[1] + 0.01})
    low = result.model_copy(update={"level": "Low", "probability": BAND_THRESHOLDS[0] - 0.01})
    announcements = ThreatAnnouncements()
    assert announcements.update(high, 60_000)
    assert not announcements.update(high, 300_000)
    assert not announcements.update(low, 310_000)
    assert announcements.update(high, 320_000)
    announcements.update(low, 330_000)
    assert not announcements.update(high, 340_000)


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
