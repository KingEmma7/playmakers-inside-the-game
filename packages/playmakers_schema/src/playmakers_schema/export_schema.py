from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter

from playmakers_schema.models import MatchEvent


def build_schema() -> dict[str, Any]:
    schema = TypeAdapter(MatchEvent).json_schema()
    schema["$id"] = "https://playmakers.local/schemas/match-event/1.0.0.json"
    schema["title"] = "Playmakers MatchEvent (v1.0.0)"
    schema["description"] = "Versioned match event schema for Playmakers / PitchSim."
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def main() -> None:
    schema = build_schema()
    print(json.dumps(schema, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
