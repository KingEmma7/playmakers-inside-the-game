from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_framework import FileCheckpointStorage, InMemoryCheckpointStorage, WorkflowCheckpoint


@dataclass(frozen=True)
class PipelineCheckpoint:
    match_id: str
    last_sequence: int
    agent_states: dict[str, dict[str, Any]]


class CheckpointManager:
    """
    Thin wrapper around Agent Framework checkpoint storage for our pipeline state.
    """

    def __init__(self, *, storage_dir: str | None = None) -> None:
        self._workflow_name = "gallery-pipeline"
        self._graph_signature_hash = "v1"

        if storage_dir is None:
            self._storage = InMemoryCheckpointStorage()
        else:
            Path(storage_dir).mkdir(parents=True, exist_ok=True)
            self._storage = FileCheckpointStorage(storage_dir)

    def save(self, ckpt: PipelineCheckpoint, *, previous_checkpoint_id: str | None = None) -> str:
        wf = WorkflowCheckpoint(
            workflow_name=self._workflow_name,
            graph_signature_hash=self._graph_signature_hash,
            previous_checkpoint_id=previous_checkpoint_id,
            state={
                "match_id": ckpt.match_id,
                "last_sequence": ckpt.last_sequence,
                "agent_states": ckpt.agent_states,
            },
        )
        return str(self._storage.save(wf))

    def load_latest(self) -> PipelineCheckpoint | None:
        latest = self._storage.get_latest(workflow_name=self._workflow_name)
        if latest is None:
            return None
        st = latest.state
        return PipelineCheckpoint(
            match_id=str(st["match_id"]),
            last_sequence=int(st["last_sequence"]),
            agent_states=dict(st.get("agent_states", {})),
        )
