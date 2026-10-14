from __future__ import annotations

import argparse
import asyncio
import json

from pitchsim.config import MatchConfig
from pitchsim.replay import replay_events
from pitchsim.sim import simulate_match

from gallery_agents.contracts import ViewerProfile
from gallery_agents.workflow import Director


async def demo(args: argparse.Namespace) -> None:
    events = await asyncio.to_thread(simulate_match, MatchConfig(seed=args.seed))
    if args.limit:
        events = events[: args.limit]
    async with Director(
        profiles=[ViewerProfile(persona=args.persona)], checkpoint_path=args.checkpoint_dir
    ) as director:
        async for event in replay_events(events, speed=args.speed):
            cues = await director.on_event(event)
            for trace in director.last_traces:
                print(json.dumps({"type": "trace", **trace.model_dump(mode="json")}))
            for cue in cues:
                print(json.dumps({"type": "cue", **cue.model_dump(mode="json")}))


def main() -> None:
    parser = argparse.ArgumentParser(prog="gallery_agents")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("demo")
    command.add_argument("--seed", type=int, default=7)
    command.add_argument("--speed", type=float, default=50)
    command.add_argument("--persona", choices=["analyst", "casual"], default="analyst")
    command.add_argument("--limit", type=int, help="Limit events for a quick smoke check")
    command.add_argument("--checkpoint-dir", default="data/checkpoints")
    asyncio.run(demo(parser.parse_args()))


if __name__ == "__main__":
    main()
