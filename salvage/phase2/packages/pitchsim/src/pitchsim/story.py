from __future__ import annotations

from pathlib import Path

import yaml

from pitchsim.config import StoryEvent


def load_story(path: str) -> list[StoryEvent]:
    data = yaml.safe_load(Path(path).read_text("utf-8"))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError("Story YAML must be a list of story events.")
    return [StoryEvent.model_validate(item) for item in data]
