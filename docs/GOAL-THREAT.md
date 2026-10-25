# Goal threat: synthetic calibration

PitchSim is synthetic. These numbers describe the simulator, not real football. This is a probability of this team scoring within five match minutes, not next-scorer odds or a promise of a goal.

Reproduce: `.venv/bin/python scripts/calibrate_threat.py --fit`. No credentials or external data. Standard-library logistic regression (slope ridge 2); seeds 1000–1199 tune coefficients and tercile thresholds, seeds 2000–2199 are held out. Seed 382 is in neither. Every integer match minute 0–85 per team; late censored horizons excluded. Labels use strictly future goals through +5 minutes. Features use only the prefix through sampling time; goals reset both windows, including their associated shots. No labels, ground truth, shot outcomes, clock or seed enter the predictors.

Features: exponentially decayed (180-second time constant), last five minutes: final-third entries, box actions, shots, summed existing shot xG, attacking-third action share, high ball wins, completed final-third passes, latest observed territory decaying to midfield. Home attacks increasing x in PitchSim in both halves. Counts scaled by 5,5,2,1,1,5,10,1. Coefficients follow that order after the intercept.

Coefficients: `(-2.9210297355, 0.2933119107, 0.1954572702, 0.2024326988, -0.5208620475, 0.1424340832, -0.3269378625, 0.0943204256, 0.2960794962)`. Thresholds: `(0.06537326686186828, 0.07398210085765804)` (Low / Medium / High).

Tuning base rate: 7.0291%; held-out base rate: 7.4157%; held-out N=34400.
Brier: 0.068587; tuning-base-rate baseline Brier: 0.068673.

| Held-out band | Mean predicted | Observed next-5-min goal rate | Count |
| --- | ---: | ---: | ---: |
| Low | 6.0725% | 6.3196% | 11314 |
| Medium | 6.9589% | 7.3702% | 11560 |
| High | 8.0399% | 8.5372% | 11526 |

| Held-out probability bin | Mean predicted | Observed | Count |
| --- | ---: | ---: | ---: |
| 4%–6% | 5.7673% | 5.5970% | 4556 |
| 6%–8% | 6.9591% | 7.5464% | 24727 |
| 8%–10% | 8.4792% | 8.4121% | 5076 |
| 10%–100% | 10.3403% | 7.3171% | 41 |

AUC: 0.5392. Overlapping horizons are correlated; no independent-sample significance claim. Band thresholds are tuning terciles, not real-world safety levels. Weak discrimination or calibration is reported as measured.

## Seed 382 (separate illustrative replay)

High announcements use hysteresis (rearm below Medium) and a three-minute per-team cooldown. These are all rises, including false alarms; goals are not guaranteed.

- High rise 0.79 min: HOME, 7.56%; next same-team goal: 2.00 min.
- Goal 2.00 min: HOME (2').
- High rise 2.82 min: AWAY, 7.44%; next same-team goal: 61.37 min.
- High rise 5.17 min: HOME, 7.41%; next same-team goal: 14.91 min.
- High rise 7.56 min: AWAY, 7.48%; next same-team goal: 61.37 min.
- High rise 9.74 min: HOME, 7.57%; next same-team goal: 14.91 min.
- High rise 13.18 min: AWAY, 7.68%; next same-team goal: 61.37 min.
- High rise 14.50 min: HOME, 7.49%; next same-team goal: 14.91 min.
- Goal 14.91 min: HOME (15').
- High rise 16.57 min: AWAY, 7.49%; next same-team goal: 61.37 min.
- High rise 18.09 min: HOME, 7.76%; next same-team goal: 19.38 min.
- Goal 19.38 min: HOME (20').
- High rise 21.81 min: AWAY, 7.67%; next same-team goal: 61.37 min.
- High rise 25.57 min: AWAY, 7.44%; next same-team goal: 61.37 min.
- High rise 27.25 min: HOME, 7.51%; next same-team goal: none min.
- High rise 30.53 min: AWAY, 7.85%; next same-team goal: 61.37 min.
- High rise 32.42 min: HOME, 7.93%; next same-team goal: none min.
- High rise 39.12 min: HOME, 7.47%; next same-team goal: none min.
- High rise 46.81 min: AWAY, 7.47%; next same-team goal: 61.37 min.
- High rise 47.88 min: HOME, 7.48%; next same-team goal: none min.
- High rise 53.81 min: HOME, 7.49%; next same-team goal: none min.
- High rise 55.28 min: AWAY, 7.48%; next same-team goal: 61.37 min.
- Goal 61.37 min: AWAY (62').
- High rise 61.74 min: AWAY, 7.50%; next same-team goal: 70.89 min.
- High rise 64.57 min: HOME, 7.62%; next same-team goal: none min.
- High rise 67.97 min: AWAY, 7.43%; next same-team goal: 70.89 min.
- Goal 70.89 min: AWAY (71').
- High rise 71.22 min: AWAY, 7.50%; next same-team goal: none min.
- High rise 72.29 min: HOME, 7.60%; next same-team goal: none min.
- High rise 76.21 min: HOME, 7.50%; next same-team goal: none min.
- High rise 82.58 min: HOME, 7.42%; next same-team goal: none min.
- High rise 83.62 min: AWAY, 7.71%; next same-team goal: none min.
- High rise 86.13 min: HOME, 7.54%; next same-team goal: none min.
- High rise 89.11 min: AWAY, 7.49%; next same-team goal: none min.
