from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from pitchsim.calibration import load_calibration_targets
from pitchsim.config import MatchConfig, StoryEvent
from pitchsim.metrics import MatchMetrics, compute_metrics
from pitchsim.sim import simulate_match


@dataclass(frozen=True)
class CalibrationCheck:
    name: str
    value: float
    min_value: float
    max_value: float
    ok: bool


def _range_from_targets(targets: dict[str, Any], key: str) -> tuple[float, float]:
    k = targets["targets"][key]
    return float(k["min"]), float(k["max"])


def validate_matches(
    matches: int,
    seed: int = 0,
    story: list[StoryEvent] | None = None,
) -> tuple[list[MatchMetrics], list[CalibrationCheck]]:
    targets = load_calibration_targets()
    metrics: list[MatchMetrics] = []
    for i in range(matches):
        cfg = MatchConfig(seed=seed + i, story=list(story or []))
        events = simulate_match(cfg)
        metrics.append(compute_metrics(events))

    passes = [m.passes for m in metrics]
    shots = [m.shots for m in metrics]
    goals = [m.goals for m in metrics]
    pass_acc = [m.pass_accuracy for m in metrics]
    fouls = [m.fouls for m in metrics]

    checks: list[CalibrationCheck] = []

    p_min, p_max = _range_from_targets(targets, "passes_per_match")
    checks.append(
        CalibrationCheck(
            name="passes_per_match (mean)",
            value=statistics.fmean(passes),
            min_value=p_min,
            max_value=p_max,
            ok=(p_min <= statistics.fmean(passes) <= p_max),
        )
    )
    s_min, s_max = _range_from_targets(targets, "shots_per_match")
    checks.append(
        CalibrationCheck(
            name="shots_per_match (mean)",
            value=statistics.fmean(shots),
            min_value=s_min,
            max_value=s_max,
            ok=(s_min <= statistics.fmean(shots) <= s_max),
        )
    )
    g_min, g_max = _range_from_targets(targets, "goals_per_match_mean")
    checks.append(
        CalibrationCheck(
            name="goals_per_match (mean)",
            value=statistics.fmean(goals),
            min_value=g_min,
            max_value=g_max,
            ok=(g_min <= statistics.fmean(goals) <= g_max),
        )
    )
    a_min, a_max = _range_from_targets(targets, "pass_accuracy_mean")
    checks.append(
        CalibrationCheck(
            name="pass_accuracy (mean)",
            value=statistics.fmean(pass_acc),
            min_value=a_min,
            max_value=a_max,
            ok=(a_min <= statistics.fmean(pass_acc) <= a_max),
        )
    )
    f_min, f_max = _range_from_targets(targets, "fouls_per_match")
    checks.append(
        CalibrationCheck(
            name="fouls_per_match (mean)",
            value=statistics.fmean(fouls),
            min_value=f_min,
            max_value=f_max,
            ok=(f_min <= statistics.fmean(fouls) <= f_max),
        )
    )

    return metrics, checks


def print_report(metrics: list[MatchMetrics], checks: list[CalibrationCheck]) -> bool:
    passes = [m.passes for m in metrics]
    shots = [m.shots for m in metrics]
    goals = [m.goals for m in metrics]
    pass_acc = [m.pass_accuracy for m in metrics]
    fouls = [m.fouls for m in metrics]

    def line(name: str, xs: list[float], unit: str = "") -> str:
        return (
            f"- {name}: mean={statistics.fmean(xs):.2f}{unit} "
            f"(p10={statistics.quantiles(xs, n=10)[0]:.2f}{unit}, "
            f"p90={statistics.quantiles(xs, n=10)[-1]:.2f}{unit})"
        )

    print("PitchSim calibration report")
    print(f"- matches: {len(metrics)}")
    print(line("passes/match", [float(x) for x in passes]))
    print(line("shots/match", [float(x) for x in shots]))
    print(line("goals/match", [float(x) for x in goals]))
    print(line("pass accuracy", pass_acc))
    print(line("fouls/match", [float(x) for x in fouls]))
    print("")

    ok = True
    for c in checks:
        status = "OK" if c.ok else "OUT_OF_RANGE"
        ok = ok and c.ok
        print(f"{status:12} {c.name}: {c.value:.3f} (target {c.min_value}..{c.max_value})")
    return ok
