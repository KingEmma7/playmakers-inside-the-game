# Goal threat: synthetic calibration

PitchSim is synthetic. These numbers describe the simulator, not real football. This estimates the probability of this team scoring within the horizon, not next-scorer odds or a promise of a goal.

## Mechanism and causal features

In `sim.py`, the next action belongs to the current possession team. Shot probability is a baseline plus `shape.shot_bonus`: +0.008 beyond 70 m, +0.07 in the box and +0.6 in the central box (before action-probability normalisation). Conversion is 0.688 × exp(−distance/17.5), clipped and reduced by pressure. Pass/carry targets advance from deep positions, recycle near the box and can reset backwards; turnovers and every shot end the spell. Consequently a five-minute pressure average loses much of the immediate possession/geometry signal as play changes hands.

Features in runtime order: current possession; current team-relative ball x/105; possession × territory; possession × exp(−goal distance/25); possession in central box; possession in final third; continuous time since entering the final third (minutes, capped at 3, reset on turnover/exit); mean territory of the last five spatial observations; decayed attacking-third seconds/60; third entries/3; recent shot count; recent existing shot xG. History is bounded at five minutes with a 60-second decay. Third occupation integrates the preceding observed state between spatial observations, with each interval capped at 60 seconds. All observations contribute evidence. Home attacks increasing x in both halves.

No future events, ground_truth, labels, shot outcomes, seed or absolute clock enter predictors. Every shot clears current possession until the observed restart, identically for every outcome; goals and period starts clear history including the associated shot. Failed passes clear possession until the explicit turnover. Foul/card/substitution teams do not claim possession. Strictly future goals are evaluation labels only; same-timestamp goals never count as future hits.

## Fixed split and horizons

Reproduce: `.venv/bin/python scripts/calibrate_threat.py --fit`. No credentials or external data; standard-library logistic regression, slope ridge 2. Seeds 1000–1199 fit each horizon and its thresholds; 2000–2199 are held out. Seed 382 is separate and never tunes coefficients or alert policy. All four horizons use identical integer-minute snapshots 0–85, both teams (34,400 per split), avoiding right censoring and making comparisons use the same prefixes. Baseline Brier predicts the tuning prevalence on held-out rows.

The commentary horizon is **2 match minutes**, selected for immediate possession/geometry relevance before inspecting held-out scores. Wording says ‘in the next few minutes’. Five-minute results remain below. Low/Medium boundary is the tuning median; High starts at the tuning 99th percentile, not a tercile. These are relative bands, not real-world safety levels.

| Horizon | AUC | Brier | Base Brier | Held-out base rate | High observed | Medium observed | Low observed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 min | 0.7225 | 0.014708 | 0.014945 | 1.517% | 12.308% | 2.241% | 0.613% |
| 2 min | 0.6262 | 0.028988 | 0.029239 | 3.015% | 12.610% | 3.824% | 2.030% |
| 3 min | 0.5834 | 0.042812 | 0.043034 | 4.506% | 12.921% | 5.283% | 3.561% |
| 5 min | 0.5464 | 0.068483 | 0.068673 | 7.416% | 15.517% | 8.126% | 6.548% |

Overlapping horizons and repeated match observations are correlated; no independent-sample significance claim. Most High states will not be followed by a goal. Brier improvements must be read against the rare-event baseline, not interpreted as proof of strong predictive skill.

## Commentary alert evaluation

Runtime hysteresis rearms below Medium, with a ten-minute per-team cooldown. Cooldown-blocked entries do not consume the rearm. Thresholds are fitted on minute snapshots; calls below are replayed at every event, exactly as runtime. Counts include all calls; hit rates use only calls with a complete horizon before 90 minutes, reporting late censored calls separately. A hit requires a strictly later same-team goal within two minutes. Multiple calls can precede the same goal; hits are not distinct goals.

The 99th-percentile High boundary and ten-minute cooldown give 7.55 calls/match on tuning seeds 1000–1039. Policy choice used tuning alert frequency only, not held-out or seed-382 goal hits. The 90th percentile was still too frequent in tuning (15.18 calls/match with this cooldown).

Held-out: **7.54 calls/match**, 1508 total; **222/1477 (15.03%)** complete-horizon calls followed by a same-team goal; 31 censored calls. The unconditional event-time same-team goal rate is 3.01% (18533/616494 complete-horizon team/event opportunities); the integer-minute base is in the table. This controls sampling cadence, not selection or match difficulty.

## Seed 382 (separate illustrative replay)

6 calls; 2/6 complete-horizon hits; 0 censored. All rises, including false alarms, follow.

Successful seed-382 calls are only seconds before the goals (see lead times below). This is detection of imminent box danger, not demonstrated reliable multi-minute anticipation; speech delivery could arrive too late. The other three goals have no same-team call in the preceding horizon.

| Call minute | Team | Probability | Next same-team goal | Within horizon? |
| ---: | --- | ---: | ---: | --- |
| 1.94 | HOME | 13.51% | 2.00 | yes |
| 14.90 | HOME | 14.98% | 14.91 | yes |
| 49.65 | AWAY | 7.61% | 61.37 | no |
| 68.17 | AWAY | 15.06% | 70.89 | no |
| 81.64 | AWAY | 6.93% | none | no |
| 82.79 | HOME | 16.11% | none | no |

| Goal (display minute) | Team | Preceding same-team calls within horizon | Lead time (seconds) |
| --- | --- | --- | --- |
| 2.00 (2′) | HOME | 1.94 | 3.7 |
| 14.91 (15′) | HOME | 14.90 | 0.4 |
| 19.38 (20′) | HOME | none | — |
| 61.37 (62′) | AWAY | none | — |
| 70.89 (71′) | AWAY | none | — |

### 1-minute fit

Coefficients: `(-5.5384191264, 0.4836316066, 0.7392896686, 0.5389550115, 1.4841367283, 1.0943467706, 0.0852422136, -0.0086868803, 0.3148396348, 0.3145275856, -0.3714745234, -0.056161341, 0.1718238195)`. Thresholds: `(0.008824524996105584, 0.050100756928546354)`. Tuning base: 1.4302%.

| Band | Mean predicted | Observed | Count |
| --- | ---: | ---: | ---: |
| Low | 0.6096% | 0.6129% | 17295 |
| Medium | 2.1135% | 2.2408% | 16780 |
| High | 10.6933% | 12.3077% | 325 |

### 2-minute fit

Coefficients: `(-4.0493423422, 0.1550327826, 0.7691634777, 0.1744049859, 1.36556686, 0.887465536, -0.0785956736, 0.2483636707, -0.3611696465, 0.2011619544, -0.1135153728, -0.0968485985, 0.1517067988)`. Thresholds: `(0.023521929166955977, 0.06746503590763081)`. Tuning base: 2.8634%.

| Band | Mean predicted | Observed | Count |
| --- | ---: | ---: | ---: |
| Low | 1.9848% | 2.0299% | 17193 |
| Medium | 3.5964% | 3.8243% | 16866 |
| High | 11.8844% | 12.6100% | 341 |

### 3-minute fit

Coefficients: `(-3.3313752687, -0.0188520735, 0.5302181249, 0.1246232493, 1.3370794285, 0.876421192, -0.1299082537, 0.1790401026, -0.5081331787, 0.3566670966, -0.0648370992, 0.0361708998, -0.0158774978)`. Thresholds: `(0.03809512768028439, 0.07941199615938915)`. Tuning base: 4.2616%.

| Band | Mean predicted | Observed | Count |
| --- | ---: | ---: | ---: |
| Low | 3.4932% | 3.5610% | 17102 |
| Medium | 4.8641% | 5.2827% | 16942 |
| High | 13.4546% | 12.9213% | 356 |

### 5-minute fit

Coefficients: `(-2.727525102, -0.0761904767, 0.4721629111, 0.0751231157, 1.3943399706, 0.6387979514, -0.1896487223, 0.1785439511, -0.5657350761, 0.2935829584, 0.1645373183, 0.0385852314, -0.0432823078)`. Thresholds: `(0.06564800943598972, 0.11574217644327896)`. Tuning base: 7.0291%.

| Band | Mean predicted | Observed | Count |
| --- | ---: | ---: | ---: |
| Low | 6.1080% | 6.5483% | 17119 |
| Medium | 7.7743% | 8.1261% | 16933 |
| High | 16.9402% | 15.5172% | 348 |
