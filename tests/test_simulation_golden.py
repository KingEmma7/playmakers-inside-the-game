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
    1: "fce391a41de92dfb60df3bb1f7e0f709f323df1951520a4ffe4a74648ae4c7a5",
    7: "275d3e42e1befa2f266b209fd2a49ef1dfb32851b888bdfe5d40eba457a3092b",
    42: "f71438002679e4c85ea630489b0cf00119e8c8d01a45dad7872987b685b598f2",
}
ROLLOUTS_SEED7_AT_1200 = [
    [4, 1],
    [4, 1],
    [4, 1],
    [4, 1],
    [5, 1],
    [4, 1],
    [4, 1],
    [4, 1],
    [6, 1],
    [4, 1],
    [4, 2],
    [4, 1],
    [4, 2],
    [4, 1],
    [5, 1],
    [4, 2],
    [4, 1],
    [5, 1],
    [4, 1],
    [4, 1],
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
