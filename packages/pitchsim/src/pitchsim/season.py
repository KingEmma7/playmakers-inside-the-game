from __future__ import annotations

import gzip
import json
from pathlib import Path

from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match


def generate_season_dataset(
    *,
    matches: int = 380,
    seed: int = 0,
    out_path: str,
) -> Path:
    """
    Generate a season-scale synthetic dataset as newline-delimited JSON (optionally gzipped).

    Each line is a single MatchEvent dict.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    open_fn = gzip.open if out.suffix == ".gz" else open
    with open_fn(out, "wt", encoding="utf-8") as f:  # type: ignore[arg-type]
        for i in range(matches):
            cfg = MatchConfig(seed=seed + i)
            events = simulate_match(cfg)
            for ev in events:
                f.write(json.dumps(ev.model_dump(mode="json"), separators=(",", ":")))
                f.write("\n")
    return out
