"""Reproduce synthetic calibration: .venv/bin/python scripts/calibrate_threat.py --fit."""

from __future__ import annotations

import argparse
import math
import re
from itertools import groupby
from pathlib import Path

from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_stats import threat

HORIZONS = (1, 2, 3, 5)
SELECTED = 2  # Chosen for commentary before examining held-out results.
Row = tuple[list[float], tuple[int, ...]]


def samples(seeds: range) -> list[Row]:
    rows = []
    for seed in seeds:
        events = simulate_match(MatchConfig(seed=seed))
        tracker = threat.ThreatTracker()
        goals = [e for e in events if e.event_type == "goal"]
        index = 0
        # Common support for all horizons: minute 0..85, both teams.
        for minute in range(86):
            now = minute * 60_000
            while index < len(events) and events[index].clock_ms <= now:
                tracker.ingest(events[index])
                index += 1
            for side in ("HOME", "AWAY"):
                team = events[0].match_id + "_" + side
                prediction = tracker.predict(team, now)
                labels = tuple(
                    int(
                        any(
                            g.scoring_team_id == team and now < g.clock_ms <= now + h * 60_000
                            for g in goals
                        )
                    )
                    for h in HORIZONS
                )
                rows.append(([1.0, *prediction.features.values()], labels))
        if seed % 25 == 0:
            print(f"Sampled seed {seed}", flush=True)
    return rows


def probability(x: list[float], coefficients: tuple[float, ...]) -> float:
    return 1 / (
        1 + math.exp(-max(-30, min(30, sum(a * b for a, b in zip(x, coefficients, strict=True)))))
    )


def fit(rows: list[Row], horizon_index: int) -> tuple[float, ...]:
    # Newton/IRLS, slope-only ridge 2; standard library, no extra dependencies.
    n = len(rows[0][0])
    coefficients = [-4.0] + [0.0] * (n - 1)
    for _ in range(40):
        gradient = [0.0] * n
        matrix = [[0.0] * n for _ in range(n)]
        for x, labels in rows:
            p = probability(x, tuple(coefficients))
            variance = p * (1 - p)
            for i in range(n):
                gradient[i] += x[i] * (labels[horizon_index] - p)
                weighted = x[i] * variance
                for j in range(i + 1):
                    matrix[i][j] += weighted * x[j]
        for i in range(n):
            for j in range(i):
                matrix[j][i] = matrix[i][j]
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
        # Damped Newton: rare central-box rows can otherwise overshoot badly.
        step = 1.0 / max(1.0, max(abs(v) for v in delta))
        coefficients = [a + step * b for a, b in zip(coefficients, delta, strict=True)]
        if max(abs(v) for v in delta) < 1e-7:
            break
    else:
        raise RuntimeError("Threat logistic fit did not converge")
    return tuple(round(c, 10) for c in coefficients)


def auc(scored: list[tuple[float, int]]) -> float:
    negatives = wins = 0.0
    for _, group_rows in groupby(sorted(scored), key=lambda row: row[0]):
        group = [y for _, y in group_rows]
        pos, neg = sum(group), len(group) - sum(group)
        wins += pos * (negatives + neg / 2)
        negatives += neg
    return wins / (sum(y for _, y in scored) * negatives)


def replay_calls(
    seed: int,
) -> tuple[list[tuple[float, str, float, float | None]], list[tuple[float, str]], tuple[int, int]]:
    events = simulate_match(MatchConfig(seed=seed))
    goals = [
        (e.clock_ms / 60_000, e.scoring_team_id.rsplit("_", 1)[-1])
        for e in events
        if e.event_type == "goal"
    ]
    tracker, announcements = threat.ThreatTracker(), threat.ThreatAnnouncements()
    calls = []
    positive_opportunities = opportunities = 0
    for e in events:
        tracker.ingest(e)
        for side in ("HOME", "AWAY"):
            now = e.clock_ms / 60_000
            if now <= 90 - SELECTED:
                opportunities += 1
                positive_opportunities += int(
                    any(team == side and now < minute <= now + SELECTED for minute, team in goals)
                )
            prediction = tracker.predict(e.match_id + "_" + side)
            if announcements.update(prediction, e.clock_ms):
                following = next(
                    (
                        minute
                        for minute, team in goals
                        if team == side and minute > e.clock_ms / 60_000
                    ),
                    None,
                )
                calls.append((e.clock_ms / 60_000, side, prediction.probability, following))
    return calls, goals, (positive_opportunities, opportunities)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fit", action="store_true", help="Regenerate selected runtime constants as well as report"
    )
    args = parser.parse_args()
    assert threat.HORIZON_MS == SELECTED * 60_000
    tuning = samples(range(1000, 1200))
    models = []
    for i, horizon in enumerate(HORIZONS):
        coefficients = fit(tuning, i)
        predictions = sorted(probability(x, coefficients) for x, _ in tuning)
        thresholds = (predictions[len(predictions) // 2], predictions[99 * len(predictions) // 100])
        models.append((coefficients, thresholds))
        print(f"Fitted {horizon} min: {coefficients}; thresholds {thresholds}", flush=True)
    coefficients, thresholds = models[HORIZONS.index(SELECTED)]
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
    tuning_calls = sum(len(replay_calls(seed)[0]) for seed in range(1000, 1040)) / 40
    held = samples(range(2000, 2200))
    lines = [
        "# Goal threat: synthetic calibration",
        "",
        "PitchSim is synthetic. These numbers describe the simulator, not real football. This estimates the probability of this team scoring within the horizon, not next-scorer odds or a promise of a goal.",
        "",
        "## Mechanism and causal features",
        "",
        "In `sim.py`, the next action belongs to the current possession team. Shot probability is a baseline plus `shape.shot_bonus`: +0.008 beyond 70 m, +0.07 in the box and +0.6 in the central box (before action-probability normalisation). Conversion is 0.688 × exp(−distance/17.5), clipped and reduced by pressure. Pass/carry targets advance from deep positions, recycle near the box and can reset backwards; turnovers and every shot end the spell. Consequently a five-minute pressure average loses much of the immediate possession/geometry signal as play changes hands.",
        "",
        "Features in runtime order: current possession; current team-relative ball x/105; possession × territory; possession × exp(−goal distance/25); possession in central box; possession in final third; continuous time since entering the final third (minutes, capped at 3, reset on turnover/exit); mean territory of the last five spatial observations; decayed attacking-third seconds/60; third entries/3; recent shot count; recent existing shot xG. History is bounded at five minutes with a 60-second decay. Third occupation integrates the preceding observed state between spatial observations, with each interval capped at 60 seconds. All observations contribute evidence. Home attacks increasing x in both halves.",
        "",
        "No future events, ground_truth, labels, shot outcomes, seed or absolute clock enter predictors. Every shot clears current possession until the observed restart, identically for every outcome; goals and period starts clear history including the associated shot. Failed passes clear possession until the explicit turnover. Foul/card/substitution teams do not claim possession. Strictly future goals are evaluation labels only; same-timestamp goals never count as future hits.",
        "",
        "## Fixed split and horizons",
        "",
        "Reproduce: `.venv/bin/python scripts/calibrate_threat.py --fit`. No credentials or external data; standard-library logistic regression, slope ridge 2. Seeds 1000–1199 fit each horizon and its thresholds; 2000–2199 are held out. Seed 382 is separate and never tunes coefficients or alert policy. All four horizons use identical integer-minute snapshots 0–85, both teams (34,400 per split), avoiding right censoring and making comparisons use the same prefixes. Baseline Brier predicts the tuning prevalence on held-out rows.",
        "",
        "The commentary horizon is **2 match minutes**, selected for immediate possession/geometry relevance before inspecting held-out scores. Wording says ‘in the next few minutes’. Five-minute results remain below. Low/Medium boundary is the tuning median; High starts at the tuning 99th percentile, not a tercile. These are relative bands, not real-world safety levels.",
        "",
        "| Horizon | AUC | Brier | Base Brier | Held-out base rate | High observed | Medium observed | Low observed |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    details = []
    for i, (horizon, (cs, ts)) in enumerate(zip(HORIZONS, models, strict=True)):
        scored = [(probability(x, cs), labels[i]) for x, labels in held]
        base = sum(labels[i] for _, labels in tuning) / len(tuning)
        observed = sum(y for _, y in scored) / len(scored)
        brier = sum((p - y) ** 2 for p, y in scored) / len(scored)
        baseline = sum((base - y) ** 2 for _, y in scored) / len(scored)
        bands = [
            [(p, y) for p, y in scored if lo <= p < hi]
            for lo, hi in ((0, ts[0]), (ts[0], ts[1]), (ts[1], 1.01))
        ]
        rates = [sum(y for _, y in band) / len(band) for band in bands]
        lines.append(
            f"| {horizon} min | {auc(scored):.4f} | {brier:.6f} | {baseline:.6f} | {observed:.3%} | {rates[2]:.3%} | {rates[1]:.3%} | {rates[0]:.3%} |"
        )
        details += [
            "",
            f"### {horizon}-minute fit",
            "",
            f"Coefficients: `{cs}`. Thresholds: `{ts}`. Tuning base: {base:.4%}.",
            "",
            "| Band | Mean predicted | Observed | Count |",
            "| --- | ---: | ---: | ---: |",
        ]
        for name, band in zip(("Low", "Medium", "High"), bands, strict=True):
            details.append(
                f"| {name} | {sum(p for p, _ in band) / len(band):.4%} | {sum(y for _, y in band) / len(band):.4%} | {len(band)} |"
            )
    lines += [
        "",
        "Overlapping horizons and repeated match observations are correlated; no independent-sample significance claim. Most High states will not be followed by a goal. Brier improvements must be read against the rare-event baseline, not interpreted as proof of strong predictive skill.",
        "",
        "## Commentary alert evaluation",
        "",
        "Runtime hysteresis rearms below Medium, with a ten-minute per-team cooldown. Cooldown-blocked entries do not consume the rearm. Thresholds are fitted on minute snapshots; calls below are replayed at every event, exactly as runtime. Counts include all calls; hit rates use only calls with a complete horizon before 90 minutes, reporting late censored calls separately. A hit requires a strictly later same-team goal within two minutes. Multiple calls can precede the same goal; hits are not distinct goals.",
        "",
    ]
    lines += [
        f"The 99th-percentile High boundary and ten-minute cooldown give {tuning_calls:.2f} calls/match on tuning seeds 1000–1039. Policy choice used tuning alert frequency only, not held-out or seed-382 goal hits. The 90th percentile was still too frequent in tuning (15.18 calls/match with this cooldown).",
        "",
    ]
    all_calls = []
    positive_opportunities = opportunities = 0
    for seed in range(2000, 2200):
        calls, _, (positive, total) = replay_calls(seed)
        positive_opportunities += positive
        opportunities += total
        all_calls.extend(calls)
        if seed % 25 == 0:
            print(f"Replayed alerts seed {seed}", flush=True)
    eligible = [c for c in all_calls if c[0] <= 90 - SELECTED]
    hits = sum(c[3] is not None and c[0] < c[3] <= c[0] + SELECTED for c in eligible)
    lines += [
        f"Held-out: **{len(all_calls) / 200:.2f} calls/match**, {len(all_calls)} total; **{hits}/{len(eligible)} ({hits / len(eligible):.2%})** complete-horizon calls followed by a same-team goal; {len(all_calls) - len(eligible)} censored calls. The unconditional event-time same-team goal rate is {positive_opportunities / opportunities:.2%} ({positive_opportunities}/{opportunities} complete-horizon team/event opportunities); the integer-minute base is in the table. This controls sampling cadence, not selection or match difficulty.",
        "",
        "## Seed 382 (separate illustrative replay)",
        "",
    ]
    calls, goals, _ = replay_calls(382)
    eligible = [c for c in calls if c[0] <= 90 - SELECTED]
    hits = sum(c[3] is not None and c[0] < c[3] <= c[0] + SELECTED for c in eligible)
    lines += [
        f"{len(calls)} calls; {hits}/{len(eligible)} complete-horizon hits; {len(calls) - len(eligible)} censored. All rises, including false alarms, follow.",
        "",
        "Successful seed-382 calls are only seconds before the goals (see lead times below). This is detection of imminent box danger, not demonstrated reliable multi-minute anticipation; speech delivery could arrive too late. The other three goals have no same-team call in the preceding horizon.",
        "",
        "| Call minute | Team | Probability | Next same-team goal | Within horizon? |",
        "| ---: | --- | ---: | ---: | --- |",
    ]
    for minute, side, p, following in calls:
        hit = following is not None and minute < following <= minute + SELECTED
        next_goal = f"{following:.2f}" if following is not None else "none"
        outcome = "censored" if minute > 90 - SELECTED else "yes" if hit else "no"
        lines.append(f"| {minute:.2f} | {side} | {p:.2%} | {next_goal} | {outcome} |")
    lines += [
        "",
        "| Goal (display minute) | Team | Preceding same-team calls within horizon | Lead time (seconds) |",
        "| --- | --- | --- | --- |",
    ]
    for minute, side in goals:
        preceding = [
            f"{c[0]:.2f}" for c in calls if c[1] == side and minute - SELECTED <= c[0] < minute
        ]
        leads = [
            f"{(minute - c[0]) * 60:.1f}"
            for c in calls
            if c[1] == side and minute - SELECTED <= c[0] < minute
        ]
        lines.append(
            f"| {minute:.2f} ({int(minute) + 1}′) | {side} | {', '.join(preceding) or 'none'} | {', '.join(leads) or '—'} |"
        )
    lines += details
    report = "\n".join(lines) + "\n"
    Path("docs/GOAL-THREAT.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
