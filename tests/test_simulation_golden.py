from __future__ import annotations

import hashlib
import json

import pytest
from pitchsim.config import MatchConfig, TeamStyle
from pitchsim.sim import simulate_match
from pitchsim.whatif import rollout_from_snapshot, snapshot_from_events

# Any intended change to PitchSim output must update these pins in the same commit,
# together with a fresh `python -m pitchsim validate --matches 50` run.
SIM_DIGESTS = {
    1: "ea27ce13e2f805f787509c190cd72c07356598625f2d6ccb7e6392637d3ec7b1",
    7: "69745b5a5b7538a63c87f8227248e93e72c677dd4d6148ce9b329eaf566ceaba",
    42: "4b32073e01d3cbdd3a7b0705ffeacea0e4beea0c5cfb838479cf1602ba64106b",
}
ROLLOUTS_SEED7_AT_1200 = [
    [3, 2],
    [3, 2],
    [2, 2],
    [2, 3],
    [3, 2],
    [2, 2],
    [2, 3],
    [2, 3],
    [2, 3],
    [2, 2],
    [2, 2],
    [2, 2],
    [3, 2],
    [2, 2],
    [3, 2],
    [4, 4],
    [3, 2],
    [3, 2],
    [2, 2],
    [2, 4],
]


@pytest.mark.parametrize("seed", sorted(SIM_DIGESTS))
def test_simulated_match_is_byte_identical_to_pinned_digest(seed: int) -> None:
    events = simulate_match(MatchConfig(seed=seed))
    payload = json.dumps([event.model_dump(mode="json") for event in events])
    assert hashlib.sha256(payload.encode()).hexdigest() == SIM_DIGESTS[seed]


def test_whatif_rollouts_match_pinned_scores() -> None:
    events = simulate_match(MatchConfig(seed=7))
    snapshot = snapshot_from_events(events[:1200], home_style=TeamStyle(), away_style=TeamStyle())
    scores = [list(rollout_from_snapshot(snapshot, rollout_seed=s)) for s in range(20)]
    assert scores == ROLLOUTS_SEED7_AT_1200
