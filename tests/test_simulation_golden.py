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
    1: "f4ebf1f3b9e8dd19164d609ad2446ebd9dff7f45e846adbdbea7b61dbdddd79a",
    7: "c9c34705f2dc6e92bc5961d549b26a6767e7fee4388b226dcc99106e948eae2b",
    42: "87b56c3629f35b28d6dfe9611461c94259d1b15d41ec4b471843598215061fb4",
}
ROLLOUTS_SEED7_AT_1200 = [
    [1, 2],
    [1, 0],
    [1, 0],
    [2, 0],
    [1, 2],
    [1, 1],
    [2, 0],
    [1, 0],
    [1, 0],
    [2, 0],
    [1, 0],
    [2, 0],
    [1, 1],
    [1, 0],
    [1, 0],
    [2, 0],
    [2, 1],
    [2, 1],
    [2, 0],
    [1, 0],
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
