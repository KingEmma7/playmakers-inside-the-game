"""Reproduce synthetic calibration: .venv/bin/python scripts/calibrate_threat.py [--fit]."""

from __future__ import annotations

import argparse
import math
import re
from itertools import groupby
from pathlib import Path

from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_stats import threat


def samples(seeds: range | list[int]) -> list[tuple[list[float], int]]:
    rows = []
    for seed in seeds:
        events = simulate_match(MatchConfig(seed=seed))
        tracker = threat.ThreatTracker()
        goals = [e for e in events if e.event_type == "goal"]
        index = 0
        # Complete five-minute horizons only: minute 0..85, each team.
        for minute in range(86):
            now = minute * 60_000
            while index < len(events) and events[index].clock_ms <= now:
                tracker.ingest(events[index])
                index += 1
            for side in ("HOME", "AWAY"):
                team = events[0].match_id + "_" + side
                prediction = tracker.predict(team, now)
                y = int(
                    any(
                        g.scoring_team_id == team and now < g.clock_ms <= now + 300_000
                        for g in goals
                    )
                )
                rows.append(([1.0, *prediction.features.values()], y))
        if seed % 25 == 0:
            print(f"Sampled seed {seed}", flush=True)
    return rows


def probability(x: list[float], coefficients: tuple[float, ...]) -> float:
    return 1 / (
        1 + math.exp(-max(-30, min(30, sum(a * b for a, b in zip(x, coefficients, strict=True)))))
    )


def fit(rows: list[tuple[list[float], int]]) -> tuple[float, ...]:
    # Newton/IRLS with a small slope-only ridge. Standard library, nine parameters.
    n = len(rows[0][0])
    coefficients = [-3.0] + [0.0] * (n - 1)
    for _ in range(15):
        gradient = [0.0] * n
        matrix = [[0.0] * n for _ in range(n)]
        for x, y in rows:
            p = probability(x, tuple(coefficients))
            for i in range(n):
                gradient[i] += x[i] * (y - p)
                for j in range(n):
                    matrix[i][j] += x[i] * x[j] * p * (1 - p)
        for i in range(n):
            ridge = 2.0 if i else 1e-6
            matrix[i][i] += ridge
            gradient[i] -= ridge * coefficients[i]
        augmented = [row + [g] for row, g in zip(matrix, gradient, strict=True)]
        for i in range(n):
            pivot = augmented[i][i]
            augmented[i] = [v / pivot for v in augmented[i]]
            for j in range(n):
                if j != i:
                    factor = augmented[j][i]
                    augmented[j] = [
                        a - factor * b for a, b in zip(augmented[j], augmented[i], strict=True)
                    ]
        delta = [row[-1] for row in augmented]
        coefficients = [a + b for a, b in zip(coefficients, delta, strict=True)]
        if max(abs(v) for v in delta) < 1e-7:
            break
    return tuple(round(c, 10) for c in coefficients)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", action="store_true")
    args = parser.parse_args()
    tuning = samples(range(1000, 1200))
    coefficients = fit(tuning) if args.fit else threat.COEFFICIENTS
    predictions = sorted(probability(x, coefficients) for x, _ in tuning)
    thresholds = (
        (predictions[len(predictions) // 3], predictions[2 * len(predictions) // 3])
        if args.fit
        else threat.BAND_THRESHOLDS
    )
    if args.fit:
        path = Path(threat.__file__)
        source = path.read_text()
        formatted = "COEFFICIENTS = (\n" + "".join(f"    {c!r},\n" for c in coefficients) + ")"
        source = re.sub(
            r"^COEFFICIENTS = .*?^BAND_THRESHOLDS = [^\n]+",
            formatted + f"\nBAND_THRESHOLDS = {thresholds!r}",
            source,
            flags=re.M | re.S,
        )
        path.write_text(source)
    threat.COEFFICIENTS, threat.BAND_THRESHOLDS = coefficients, thresholds
    held = samples(range(2000, 2200))
    base = sum(y for _, y in tuning) / len(tuning)
    observed = sum(y for _, y in held) / len(held)
    scored = [(probability(x, coefficients), y) for x, y in held]
    brier = sum((p - y) ** 2 for p, y in scored) / len(scored)
    baseline = sum((base - y) ** 2 for _, y in scored) / len(scored)
    lines = [
        "# Goal threat: synthetic calibration",
        "",
        "PitchSim is synthetic. These numbers describe the simulator, not real football. This is a probability of this team scoring within five match minutes, not next-scorer odds or a promise of a goal.",
        "",
        "Reproduce: `.venv/bin/python scripts/calibrate_threat.py --fit`. No credentials or external data. Standard-library logistic regression (slope ridge 2); seeds 1000–1199 tune coefficients and tercile thresholds, seeds 2000–2199 are held out. Seed 382 is in neither. Every integer match minute 0–85 per team; late censored horizons excluded. Labels use strictly future goals through +5 minutes. Features use only the prefix through sampling time; goals reset both windows, including their associated shots. No labels, ground truth, shot outcomes, clock or seed enter the predictors.",
        "",
        "Features: exponentially decayed (180-second time constant), last five minutes: final-third entries, box actions, shots, summed existing shot xG, attacking-third action share, high ball wins, completed final-third passes, latest observed territory decaying to midfield. Home attacks increasing x in PitchSim in both halves. Counts scaled by 5,5,2,1,1,5,10,1. Coefficients follow that order after the intercept.",
        "",
        f"Coefficients: `{coefficients}`. Thresholds: `{thresholds}` (Low / Medium / High).",
        "",
        f"Tuning base rate: {base:.4%}; held-out base rate: {observed:.4%}; held-out N={len(held)}.",
        f"Brier: {brier:.6f}; tuning-base-rate baseline Brier: {baseline:.6f}.",
        "",
        "| Held-out band | Mean predicted | Observed next-5-min goal rate | Count |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, lo, hi in (
        ("Low", 0, thresholds[0]),
        ("Medium", thresholds[0], thresholds[1]),
        ("High", thresholds[1], 1.01),
    ):
        group = [(p, y) for p, y in scored if lo <= p < hi]
        lines.append(
            f"| {name} | {sum(p for p, _ in group) / len(group):.4%} | {sum(y for _, y in group) / len(group):.4%} | {len(group)} |"
        )
    lines += [
        "",
        "| Held-out probability bin | Mean predicted | Observed | Count |",
        "| --- | ---: | ---: | ---: |",
    ]
    for lo, hi in ((0, 0.04), (0.04, 0.06), (0.06, 0.08), (0.08, 0.10), (0.10, 1.01)):
        group = [(p, y) for p, y in scored if lo <= p < hi]
        if group:
            lines.append(
                f"| {lo:.0%}–{min(hi, 1):.0%} | {sum(p for p, _ in group) / len(group):.4%} | {sum(y for _, y in group) / len(group):.4%} | {len(group)} |"
            )
    ordered = sorted(scored)
    negatives = wins = 0.0
    for _, group_rows in groupby(ordered, key=lambda row: row[0]):
        group = [y for _, y in group_rows]
        pos, neg = sum(group), len(group) - sum(group)
        wins += pos * (negatives + neg / 2)
        negatives += neg
    positives = sum(y for _, y in scored)
    lines += [
        "",
        f"AUC: {wins / (positives * negatives):.4f}. Overlapping horizons are correlated; no independent-sample significance claim. Band thresholds are tuning terciles, not real-world safety levels. Weak discrimination or calibration is reported as measured.",
        "",
        "## Seed 382 (separate illustrative replay)",
        "",
        "High announcements use hysteresis (rearm below Medium) and a three-minute per-team cooldown. These are all rises, including false alarms; goals are not guaranteed.",
        "",
    ]
    tracker, announcements = threat.ThreatTracker(), threat.ThreatAnnouncements()
    events = simulate_match(MatchConfig(seed=382))
    for e in events:
        tracker.ingest(e)
        if e.event_type == "goal":
            lines.append(
                f"- Goal {e.clock_ms / 60000:.2f} min: {e.scoring_team_id.rsplit('_', 1)[-1]} ({e.clock_ms // 60000 + 1}')."
            )
        for side in ("HOME", "AWAY"):
            prediction = tracker.predict(e.match_id + "_" + side)
            if announcements.update(prediction, e.clock_ms):
                future = [
                    g
                    for g in events
                    if g.event_type == "goal"
                    and g.scoring_team_id == prediction.team_id
                    and g.clock_ms > e.clock_ms
                ]
                next_goal = f"{future[0].clock_ms / 60000:.2f}" if future else "none"
                lines.append(
                    f"- High rise {e.clock_ms / 60000:.2f} min: {side}, {prediction.probability:.2%}; next same-team goal: {next_goal} min."
                )
    report = "\n".join(lines) + "\n"
    Path("docs/GOAL-THREAT.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
