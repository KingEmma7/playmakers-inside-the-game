from __future__ import annotations

from pitchsim.validate import validate_matches


def test_calibration_checks_within_targets_for_fixed_seed_suite() -> None:
    _metrics, checks = validate_matches(matches=50, seed=1000)
    assert all(c.ok for c in checks)
