from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

from agent_framework import Agent, BaseChatClient
from pitchsim.config import MatchConfig
from pitchsim.whatif import MatchSnapshot, rollout_from_snapshot, snapshot_from_events
from playmakers_schema.models import MatchEvent
from pydantic import BaseModel, Field

from playmakers_agents.contracts import OverlayCue


class Probabilities(BaseModel):
    win: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    loss: float = Field(ge=0, le=1)


class WhatIfMetrics(BaseModel):
    before: Probabilities
    after: Probabilities
    counterfactual: Probabilities
    win_prob_before: float
    win_prob_after: float
    delta: float
    rollouts: int


def run_batch(snapshot: MatchSnapshot, seeds: list[int]) -> Probabilities:
    outcomes = [rollout_from_snapshot(snapshot, rollout_seed=seed) for seed in seeds]
    return Probabilities(
        win=sum(h > a for h, a in outcomes) / len(seeds),
        draw=sum(h == a for h, a in outcomes) / len(seeds),
        loss=sum(h < a for h, a in outcomes) / len(seeds),
    )


def create_rollout_pool() -> ProcessPoolExecutor:
    # Spawn avoids inheriting the API event loop, sockets and shutdown signal handlers.
    return ProcessPoolExecutor(
        max_workers=min(3, os.cpu_count() or 1),
        mp_context=multiprocessing.get_context("spawn"),
    )


class WhatIfAgent:
    """Paired seeded PitchSim continuations; probabilities always refer to the home side."""

    def __init__(
        self,
        client: BaseChatClient,
        rollouts: int = 200,
        seed: int = 0,
        pool: ProcessPoolExecutor | None = None,
    ) -> None:
        if not 1 <= rollouts <= 2000:
            raise ValueError("whatif_rollouts must be between 1 and 2000")
        self.client, self.rollouts, self.seed = client, rollouts, seed
        self.pool = pool
        self._owns_pool = pool is None
        self._pending: set[asyncio.Future[Probabilities]] = set()

    @staticmethod
    def triggers(event: MatchEvent) -> bool:
        return (
            event.event_type == "goal"
            or (event.event_type == "shot" and event.xg > 0.3 and event.outcome != "goal")
            or (event.event_type == "card" and event.color == "red")
        )

    async def close(self) -> None:
        for future in self._pending:
            future.cancel()
        if self.pool and self._owns_pool:
            await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=True)
            self.pool = None

    async def evaluate(self, events: list[MatchEvent]) -> OverlayCue | None:
        event = events[-1]
        if not self.triggers(event):
            return None
        config = MatchConfig(seed=self.seed)
        after = snapshot_from_events(
            events, home_style=config.home_style, away_style=config.away_style
        )
        before = snapshot_from_events(
            events[:-1] or events, home_style=config.home_style, away_style=config.away_style
        )
        # Compare at the same clock with common random numbers to reduce Monte Carlo noise.
        before = before.model_copy(update={"clock_ms": after.clock_ms})
        home = (getattr(event, "scoring_team_id", event.team_id) or "").endswith("_HOME")
        if event.event_type == "goal":
            counter = after.model_copy(
                update={
                    "home_score": after.home_score - int(home),
                    "away_score": after.away_score - int(not home),
                }
            )
            scenario = "if the shot had been saved"
        elif event.event_type == "shot":
            counter = after.model_copy(
                update={
                    "home_score": after.home_score + int(home),
                    "away_score": after.away_score + int(not home),
                }
            )
            scenario = "if the chance had been scored"
        else:
            counter = before
            scenario = "if the red card had not been shown"
        base = int.from_bytes(hashlib.sha256(f"{self.seed}:{event.event_id}".encode()).digest()[:8])
        seeds = [base + i for i in range(self.rollouts)]
        if self.pool is None:
            self.pool = create_rollout_pool()
        loop = asyncio.get_running_loop()
        futures = [
            loop.run_in_executor(self.pool, run_batch, snapshot, seeds)
            for snapshot in (before, after, counter)
        ]
        self._pending.update(futures)
        try:
            probabilities = await asyncio.gather(*futures)
        finally:
            for future in futures:
                future.cancel()
            self._pending.difference_update(futures)
        p0, p1, pc = probabilities
        metrics = WhatIfMetrics(
            before=p0,
            after=p1,
            counterfactual=pc,
            win_prob_before=p0.win,
            win_prob_after=p1.win,
            delta=p1.win - p0.win,
            rollouts=self.rollouts,
        )
        detail = f"Home win probability changes across seeded continuations; {scenario}, the outlook differs."
        try:
            response = await asyncio.wait_for(
                Agent(
                    self.client,
                    instructions="Explain this synthetic football counterfactual in one or two sentences. "
                    "Use no numbers or additional facts; probabilities refer to home.",
                ).run(
                    json.dumps(
                        {
                            "task": "what_if_explanation",
                            "scenario": scenario,
                            "metrics": metrics.model_dump(),
                        }
                    )
                ),
                timeout=1.5,
            )
            if response.text and not any(c.isdigit() for c in response.text):
                detail = response.text
        except Exception:
            pass
        return OverlayCue(
            cue_id=f"{event.event_id}:what_if",
            clock_ms=event.clock_ms,
            template="what_if",
            priority=80,
            duration_ms=8000,
            payload={
                "headline": "What if?",
                "detail": detail,
                "scenario": scenario,
                "metrics": metrics.model_dump(),
                "perspective": "home",
            },
            evidence_event_ids=[row.event_id for row in events],
        )
