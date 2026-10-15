from __future__ import annotations

from jsonschema import Draft202012Validator
from pitchsim.config import MatchConfig
from pitchsim.sim import simulate_match
from playmakers_schema.schema import load_match_event_schema_v1


def test_events_validate_against_json_schema_v1() -> None:
    schema = load_match_event_schema_v1()
    validator = Draft202012Validator(schema)

    events = simulate_match(MatchConfig(seed=7))
    for e in events:
        errors = sorted(validator.iter_errors(e.model_dump(mode="json")), key=str)
        assert errors == []
