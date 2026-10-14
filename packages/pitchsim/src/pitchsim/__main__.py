from __future__ import annotations

import argparse
import json
import sys

from pitchsim.config import MatchConfig
from pitchsim.season import generate_season_dataset
from pitchsim.sim import simulate_match
from pitchsim.validate import print_report, validate_matches


def _cmd_validate(args: argparse.Namespace) -> int:
    metrics, checks = validate_matches(matches=args.matches, seed=args.seed)
    ok = print_report(metrics, checks)
    return 0 if ok else 2


def _cmd_simulate(args: argparse.Namespace) -> int:
    cfg = MatchConfig(seed=args.seed)
    events = simulate_match(cfg)
    for e in events:
        print(json.dumps(e.model_dump(mode="json"), separators=(",", ":")))
    return 0


def _cmd_season(args: argparse.Namespace) -> int:
    out = generate_season_dataset(matches=args.matches, seed=args.seed, out_path=args.out)
    print(str(out))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pitchsim", description="PitchSim synthetic match simulator."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser(
        "validate", help="Simulate N matches and report calibration vs targets."
    )
    p_validate.add_argument("--matches", type=int, default=50)
    p_validate.add_argument("--seed", type=int, default=0)
    p_validate.set_defaults(func=_cmd_validate)

    p_sim = sub.add_parser(
        "simulate", help="Simulate one match and print newline-delimited JSON events."
    )
    p_sim.add_argument("--seed", type=int, default=0)
    p_sim.set_defaults(func=_cmd_simulate)

    p_season = sub.add_parser(
        "season",
        help="Generate a season-scale dataset (newline-delimited MatchEvent JSON, optionally gzipped).",
    )
    p_season.add_argument("--matches", type=int, default=380)
    p_season.add_argument("--seed", type=int, default=0)
    p_season.add_argument("--out", type=str, default="data/season.match_events.jsonl.gz")
    p_season.set_defaults(func=_cmd_season)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
