from __future__ import annotations

from dataclasses import dataclass

from playmakers_schema.models import MatchEvent
from pitchsim.config import MatchConfig, TeamStyle

from playmakers_agents.agents import Director
from playmakers_agents.checkpointing import CheckpointManager, PipelineCheckpoint
from playmakers_agents.contracts import OverlayCue, ViewerProfile
from playmakers_agents.state_store import InMemoryMatchStore


@dataclass(frozen=True)
class PlaymakersPipelineConfig:
    profile: ViewerProfile
    checkpoint_dir: str | None = None
    kill_tactics_after_sequence: int | None = None
    whatif_rollouts: int = 120
    home_style: TeamStyle = TeamStyle(name="possession", tempo=1.05)
    away_style: TeamStyle = TeamStyle(name="counter", tempo=1.0)


class PlaymakersPipeline:
    """
    Phase 2 Playmakers pipeline runner.

    Runs fully offline by default. When deployed with real model clients later,
    the Director and specialist agents can be swapped to LLM-backed versions.
    """

    def __init__(self, *, match_id: str, config: PlaymakersPipelineConfig) -> None:
        self._match_id = match_id
        self._store = InMemoryMatchStore()
        self._director = Director(
            store=self._store,
            profile=config.profile,
            home_style=config.home_style,
            away_style=config.away_style,
            kill_tactics_after_sequence=config.kill_tactics_after_sequence,
            whatif_rollouts=config.whatif_rollouts,
        )
        self._ckpt = CheckpointManager(storage_dir=config.checkpoint_dir)
        self._previous_checkpoint_id: str | None = None

    @property
    def store(self) -> InMemoryMatchStore:
        return self._store

    def is_agent_dead(self, name: str) -> bool:
        return self._director.is_agent_dead(name)

    async def on_event(self, event: MatchEvent) -> list[OverlayCue]:
        cues = await self._director.on_event(self._match_id, event)

        # Persist checkpoint after processing each event.
        ckpt_id = self._ckpt.save(
            PipelineCheckpoint(
                match_id=self._match_id,
                last_sequence=int(event.sequence),  # type: ignore[attr-defined]
                agent_states=self._director.checkpoint_state(),
            ),
            previous_checkpoint_id=self._previous_checkpoint_id,
        )
        self._previous_checkpoint_id = ckpt_id

        # Failure recovery: restart tactics from checkpoint and catch up.
        if self._director.is_agent_dead("tactics"):
            latest = self._ckpt.load_latest()
            if latest is not None:
                tactics_state = latest.agent_states.get("tactics", {})
                self._director.restart_tactics(tactics_state)
                await self._director.catch_up_tactics(self._match_id)

        return cues
