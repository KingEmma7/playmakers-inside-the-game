from __future__ import annotations

from importlib import resources
from typing import Any

import yaml


def load_calibration_targets() -> dict[str, Any]:
    path = resources.files("pitchsim").joinpath("data/calibration.yaml")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
