from __future__ import annotations

import hashlib
from typing import Protocol

from agent_framework import CheckpointStorage, WorkflowCheckpoint
from pydantic import BaseModel, Field

from playmakers_agents.state_store import MatchState


class RecoveryState(BaseModel):
    schema_version: str = "1.0.0"
    match: MatchState
    agent_sequences: dict[str, int] = Field(default_factory=dict)


class RecoveryStorage(Protocol):
    async def save(self, state: RecoveryState) -> None: ...
    async def load(self, match_id: str) -> RecoveryState | None: ...


class FrameworkRecoveryStorage:
    """JSON-only state in the Framework storage protocol; Cosmos can implement the same API."""

    def __init__(self, storage: CheckpointStorage) -> None:
        self.storage = storage

    @staticmethod
    def name(match_id: str) -> str:
        return "playmakers-recovery-" + hashlib.sha256(match_id.encode()).hexdigest()[:24]

    async def save(self, state: RecoveryState) -> None:
        name = self.name(state.match.match_id)
        await self.storage.save(
            WorkflowCheckpoint(
                workflow_name=name,
                graph_signature_hash="playmakers-recovery-v1",
                checkpoint_id=name,
                state=state.model_dump(mode="json"),
            )
        )

    async def load(self, match_id: str) -> RecoveryState | None:
        checkpoint = await self.storage.get_latest(workflow_name=self.name(match_id))
        return RecoveryState.model_validate(checkpoint.state) if checkpoint else None
