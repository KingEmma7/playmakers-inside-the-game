from __future__ import annotations

from pydantic import BaseModel, Field


class KillSpec(BaseModel):
    agent: str
    minute: float = Field(ge=0, le=120)

    @classmethod
    def parse(cls, value: str | None) -> KillSpec | None:
        if value is None:
            return None
        try:
            agent, minute = value.split("@")
            if agent != "tactics":
                raise ValueError("Only tactics can be killed")
            return cls(agent=agent, minute=float(minute))
        except (ValueError, TypeError) as exc:
            raise ValueError("kill must be tactics@<minute> (0–120)") from exc


class CircuitBreaker:
    """Open after failure; allow a probe after one event, back off after repeated failures."""

    def __init__(self) -> None:
        self.failures = 0
        self.retry_sequence = -1

    def fail(self, sequence: int) -> None:
        self.failures += 1
        self.retry_sequence = sequence + min(2 ** (self.failures - 1), 16)

    def permits(self, sequence: int) -> bool:
        return sequence >= self.retry_sequence

    def reset(self) -> None:
        self.failures = 0
        self.retry_sequence = -1
