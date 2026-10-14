from __future__ import annotations

import pytest

from gallery_agents.contracts import ViewerProfile
from gallery_agents.pipeline import GalleryPipeline, GalleryPipelineConfig
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match


@pytest.mark.asyncio
async def test_pipeline_kill_fallback_and_recovery() -> None:
    events = simulate_match(MatchConfig(seed=21))
    first_goal = next(e for e in events if e.event_type == "goal")  # type: ignore[attr-defined]
    kill_seq = int(first_goal.sequence)  # type: ignore[attr-defined]

    pipeline = GalleryPipeline(
        match_id="match_21",
        config=GalleryPipelineConfig(
            profile=ViewerProfile(persona="analyst", language="en"),
            kill_tactics_after_sequence=kill_seq,
            whatif_rollouts=5,
        ),
    )

    # Run until just after the first goal.
    goal_idx = next(i for i, e in enumerate(events) if e.event_id == first_goal.event_id)  # type: ignore[attr-defined]
    for ev in events[: goal_idx + 5]:
        await pipeline.on_event(ev)

    cues = list(pipeline.store.get_or_create("match_21").overlay_cues)
    assert any(c.template == "goal_flash" for c in cues), "Expected template fallback cue on goal"

    # Pipeline should attempt a restart immediately after detecting the failure.
    assert pipeline.is_agent_dead("tactics") is False


@pytest.mark.asyncio
async def test_pipeline_personalization_and_what_if_output() -> None:
    events = simulate_match(MatchConfig(seed=7))
    pipeline = GalleryPipeline(
        match_id="match_7",
        config=GalleryPipelineConfig(
            profile=ViewerProfile(persona="casual", language="es"),
            kill_tactics_after_sequence=None,
            whatif_rollouts=5,
        ),
    )

    # Run until first goal so What-If triggers.
    for ev in events:
        cues = await pipeline.on_event(ev)
        if ev.event_type == "goal":  # type: ignore[attr-defined]
            # Expect at least one what-if cue.
            what_if_cues = [c for c in cues if c.payload.get("headline") == "¿Qué pasaría si...?"]
            assert what_if_cues, "Expected Spanish what-if headline for casual profile"
            assert any("win_prob" in (c.payload.get("metrics") or {}) for c in what_if_cues)
            # Evidence must be present for compliance.
            assert all(c.evidence_event_ids for c in what_if_cues)
            break
    else:
        raise AssertionError("No goal found; What-If was not exercised")
