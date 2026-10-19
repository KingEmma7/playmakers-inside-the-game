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
    1: "9d799342e71fd61b23574667e6799ddd0cd5ef0e9fc1a7bc0f30ca5283b94e7b",
    7: "40a955b2a1bc990dafe0ae8f1c1cdb3ead04abf233a85b611d51146cf2436c5f",
    42: "4a0dcc360221a119cfbfb60623f4c5fa446fce0ea5d7f9752b0756be20dedd7c",
}
ROLLOUTS_SEED7_AT_1200 = [
    [2, 0],
    [3, 0],
    [2, 0],
    [2, 0],
    [2, 1],
    [2, 1],
    [2, 0],
    [2, 0],
    [2, 0],
    [2, 0],
    [2, 0],
    [3, 0],
    [3, 1],
    [2, 0],
    [2, 0],
    [3, 0],
    [2, 0],
    [2, 0],
    [2, 0],
    [2, 0],
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
