from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter

from gallery_schema.models import MatchEvent


def build_schema() -> dict[str, Any]:
    schema = TypeAdapter(MatchEvent).json_schema()
    schema["$id"] = "https://gallery.local/schemas/match-event/1.0.0.json"
    schema["title"] = "Gallery MatchEvent (v1.0.0)"
    schema["description"] = "Versioned match event schema for Gallery / PitchSim."
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def main() -> None:
    schema = build_schema()
    print(json.dumps(schema, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
