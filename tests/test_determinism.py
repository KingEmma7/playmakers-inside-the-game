from __future__ import annotations

from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match


def test_simulator_is_deterministic_for_same_seed() -> None:
    cfg = MatchConfig(seed=123)
    a = simulate_match(cfg)
    b = simulate_match(cfg)

    a_dump = [e.model_dump(mode="json") for e in a]
    b_dump = [e.model_dump(mode="json") for e in b]

    assert a_dump == b_dump
