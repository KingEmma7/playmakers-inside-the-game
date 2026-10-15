from __future__ import annotations

import json
from pathlib import Path

from playmakers_schema import models

from playmakers_agents.contracts import AgentTraceEvent, OverlayCue


def main() -> None:
    directory = Path(models.__file__).parent / "schemas" / "v1"
    for model, name in ((OverlayCue, "overlay_cue"), (AgentTraceEvent, "agent_trace_event")):
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://playmakers.local/schemas/{name}/1.0.0.json"
        (directory / f"{name}.schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n"
        )


if __name__ == "__main__":
    main()
