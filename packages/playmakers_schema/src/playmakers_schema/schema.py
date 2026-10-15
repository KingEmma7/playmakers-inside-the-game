from __future__ import annotations

import json
from importlib import resources
from typing import Any


def load_match_event_schema_v1() -> dict[str, Any]:
    schema_path = resources.files("playmakers_schema").joinpath(
        "schemas/v1/match_event.schema.json"
    )
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)
