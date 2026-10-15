# playmakers-stats

Credential-free deterministic statistics with Pydantic results and event-ID evidence.
One StatsEngine handles one match, in increasing sequence order, retaining up to 50,000 events.
Time windows include both boundaries and exclude future events.

- Possession: completed passes and carries by fictional `_HOME` / `_AWAY` team suffix.
- Pressure index: mean pressure faced on passes/carries and annotated shots.
- Pass difficulty and xG: event-level simulator values; wrong event types are rejected.
- Momentum: normalized home/away difference of shots plus twice goals.
- Control vs chaos: normalized Shannon entropy of completed directed player-to-player
  pass edges, plus failed passes divided by all passes (turnover proxy).
  Empty/single-edge networks have zero entropy. Possession-change records are excluded
  from turnover counts to avoid counting the same failed pass twice.

These are explanatory proxies for synthetic football, not calibrated broadcast measurements.
