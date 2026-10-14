from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from gallery_schema.models import MatchEvent
from gallery_stats.engine import StatsEngine
from pitchsim.config import TeamStyle
from pitchsim.whatif import (
    MatchSnapshot,
    snapshot_from_events,
    win_probability_delta_for_forced_goal,
)

from gallery_agents.contracts import ComplianceDecision, Insight, OverlayCue, ViewerProfile
from gallery_agents.personalize import personalize_cue
from gallery_agents.state_store import InMemoryMatchStore


@dataclass
class AgentFailure(Exception):
    agent_name: str
    message: str


class StatsAgent:
    name = "stats"

    def __init__(self) -> None:
        self._engine: StatsEngine = StatsEngine()
        self._last_sequence: int = -1

    def checkpoint_state(self) -> dict[str, Any]:
        return {"last_sequence": self._last_sequence}

    def restore(self, state: dict[str, Any]) -> None:
        self._last_sequence = int(state.get("last_sequence", -1))

    def ingest(self, event: MatchEvent) -> None:
        self._engine.ingest(event)
        self._last_sequence = max(self._last_sequence, int(event.sequence))  # type: ignore[attr-defined]

    def momentum(self, clock_ms: int) -> dict:
        return self._engine.momentum(match_clock_ms=clock_ms).model_dump(mode="json")

    def possession(self, clock_ms: int) -> dict:
        return self._engine.possession(match_clock_ms=clock_ms).model_dump(mode="json")

    def pressure_index(self, team_id: str, clock_ms: int) -> dict:
        return self._engine.pressure_index(team_id=team_id, match_clock_ms=clock_ms).model_dump(
            mode="json"
        )


class TacticsAgent:
    name = "tactics"

    def __init__(self, *, kill_after_sequence: int | None = None) -> None:
        self._last_sequence: int = -1
        self._killed: bool = False
        self._kill_after_sequence = kill_after_sequence

    def checkpoint_state(self) -> dict[str, Any]:
        return {"last_sequence": self._last_sequence, "killed": self._killed}

    def restore(self, state: dict[str, Any]) -> None:
        self._last_sequence = int(state.get("last_sequence", -1))
        self._killed = bool(state.get("killed", False))

    async def on_event(
        self,
        *,
        match_id: str,
        event: MatchEvent,
        store: InMemoryMatchStore,
        stats: StatsAgent,
    ) -> list[Insight]:
        seq = int(event.sequence)  # type: ignore[attr-defined]
        if (
            self._kill_after_sequence is not None
            and (seq >= self._kill_after_sequence)
            and not self._killed
        ):
            self._killed = True
            raise AgentFailure(
                agent_name=self.name, message="Simulated tactics agent crash (demo kill)."
            )

        self._last_sequence = max(self._last_sequence, seq)
        t = event.event_type  # type: ignore[attr-defined]
        clock = int(event.clock_ms)  # type: ignore[attr-defined]

        insights: list[Insight] = []

        # Deterministic heuristics (offline mode): trigger on goals and high-pressure turnovers.
        if t == "goal":
            mom = stats.momentum(clock_ms=clock)
            insights.append(
                Insight(
                    insight_id=f"{match_id}:{event.event_id}:tactics:goal",
                    clock_ms=clock,
                    kind="tactics",
                    headline="Key moment",
                    detail="Momentum swing after the goal; watch how the game state shifts immediately.",
                    evidence_event_ids=[event.event_id] + list(mom["evidence"]["event_ids"]),
                    metrics={"momentum": mom},
                )
            )

        if t == "pass" and hasattr(event, "completed") and not event.completed:  # type: ignore[attr-defined]
            team_id = getattr(event, "team_id", None)
            if team_id is not None:
                p = stats.pressure_index(team_id=team_id, clock_ms=clock)
                if float(p["pressure_index"]) > 0.65:
                    insights.append(
                        Insight(
                            insight_id=f"{match_id}:{event.event_id}:tactics:press",
                            clock_ms=clock,
                            kind="tactics",
                            headline="Press forces a turnover",
                            detail="A high-pressure sequence disrupts buildup and flips possession.",
                            evidence_event_ids=[event.event_id] + list(p["evidence"]["event_ids"]),
                            metrics={"pressure_index": p},
                        )
                    )

        return insights


class StorylineAgent:
    name = "storyline"

    def __init__(self) -> None:
        self._last_sequence: int = -1
        self._theme: str | None = None

    def checkpoint_state(self) -> dict[str, Any]:
        return {"last_sequence": self._last_sequence, "theme": self._theme}

    def restore(self, state: dict[str, Any]) -> None:
        self._last_sequence = int(state.get("last_sequence", -1))
        self._theme = state.get("theme")

    async def on_event(
        self, *, match_id: str, event: MatchEvent, stats: StatsAgent
    ) -> list[Insight]:
        seq = int(event.sequence)  # type: ignore[attr-defined]
        self._last_sequence = max(self._last_sequence, seq)

        clock = int(event.clock_ms)  # type: ignore[attr-defined]
        if self._theme is None:
            self._theme = "control-vs-chaos"

        # Emit periodic storyline beats every ~8 minutes.
        if clock % (8 * 60 * 1000) < 250:
            poss = stats.possession(clock_ms=clock)
            return [
                Insight(
                    insight_id=f"{match_id}:{seq}:storyline:beat",
                    clock_ms=clock,
                    kind="storyline",
                    headline="Storyline",
                    detail="This phase of the match is being decided by control vs. chaos in midfield.",
                    evidence_event_ids=list(poss["evidence"]["event_ids"]),
                    metrics={"possession": poss, "theme": self._theme},
                )
            ]
        return []


class WhatIfAgent:
    name = "what_if"

    def __init__(self, *, rollouts: int = 120) -> None:
        self._last_sequence: int = -1
        self._rollouts = rollouts

    def checkpoint_state(self) -> dict[str, Any]:
        return {"last_sequence": self._last_sequence}

    def restore(self, state: dict[str, Any]) -> None:
        self._last_sequence = int(state.get("last_sequence", -1))

    async def on_key_moment(
        self,
        *,
        match_id: str,
        store: InMemoryMatchStore,
        home_style: TeamStyle,
        away_style: TeamStyle,
        scoring_team: str,
    ) -> Insight:
        events = list(store.get_or_create(match_id).events)
        snapshot = snapshot_from_events(events, home_style=home_style, away_style=away_style)
        delta = await asyncio.to_thread(
            win_probability_delta_for_forced_goal,
            snapshot,
            forced_scoring_team=scoring_team,
            rollouts=self._rollouts,
            seed=hash(match_id) % 10_000,
        )

        return Insight(
            insight_id=f"{match_id}:{events[-1].event_id}:whatif",
            clock_ms=int(events[-1].clock_ms),  # type: ignore[attr-defined]
            kind="what_if",
            headline="What-if",
            detail=(
                "Counterfactual rollouts suggest a measurable shift in win probability from this moment."
            ),
            evidence_event_ids=[events[-1].event_id],
            metrics={"win_prob": delta},
        )


class ComplianceAgent:
    name = "compliance"

    def checkpoint_state(self) -> dict[str, Any]:
        return {}

    def restore(self, state: dict[str, Any]) -> None:
        _ = state

    async def validate(self, cue: OverlayCue) -> ComplianceDecision:
        reasons: list[str] = []
        if not cue.evidence_event_ids:
            reasons.append("overlay_cue_missing_evidence_event_ids")
        if "Premier League" in (cue.payload.get("headline") or ""):
            reasons.append("brand_violation")
        return ComplianceDecision(ok=(len(reasons) == 0), reasons=reasons)


class GraphicsAgent:
    name = "graphics"

    def checkpoint_state(self) -> dict[str, Any]:
        return {}

    def restore(self, state: dict[str, Any]) -> None:
        _ = state

    async def build_cues(self, insights: list[Insight]) -> list[OverlayCue]:
        cues: list[OverlayCue] = []
        for ins in insights:
            cues.append(
                OverlayCue(
                    cue_id=f"cue:{ins.insight_id}",
                    clock_ms=ins.clock_ms,
                    template="lower_third",
                    payload={
                        "headline": ins.headline,
                        "detail": ins.detail,
                        "metrics": ins.metrics,
                    },
                    duration_ms=4500 if ins.kind != "what_if" else 6000,
                    priority=50 if ins.kind in ("tactics", "what_if") else 20,
                    evidence_event_ids=list(ins.evidence_event_ids),
                )
            )
        return cues

    async def template_fallback(
        self, *, match_id: str, event: MatchEvent, stats: StatsAgent
    ) -> list[OverlayCue]:
        clock = int(event.clock_ms)  # type: ignore[attr-defined]
        if event.event_type == "goal":  # type: ignore[attr-defined]
            mom = stats.momentum(clock_ms=clock)
            return [
                OverlayCue(
                    cue_id=f"cue:{match_id}:{event.event_id}:fallback",
                    clock_ms=clock,
                    template="goal_flash",
                    payload={
                        "headline": "Key moment",
                        "detail": "Goal. Graphics in template fallback while an agent recovers.",
                        "metrics": {"momentum": mom},
                    },
                    duration_ms=3500,
                    priority=90,
                    evidence_event_ids=[event.event_id] + list(mom["evidence"]["event_ids"]),
                )
            ]
        return []


class Director:
    name = "director"

    def __init__(
        self,
        *,
        store: InMemoryMatchStore,
        profile: ViewerProfile,
        home_style: TeamStyle,
        away_style: TeamStyle,
        kill_tactics_after_sequence: int | None = None,
        whatif_rollouts: int = 120,
    ) -> None:
        self._store = store
        self._profile = profile
        self._home_style = home_style
        self._away_style = away_style
        self._kill_tactics_after_sequence = kill_tactics_after_sequence

        self._stats = StatsAgent()
        self._tactics = TacticsAgent(kill_after_sequence=kill_tactics_after_sequence)
        self._storyline = StorylineAgent()
        self._whatif = WhatIfAgent(rollouts=whatif_rollouts)
        self._compliance = ComplianceAgent()
        self._graphics = GraphicsAgent()

        self._agent_dead: dict[str, bool] = {}

    def checkpoint_state(self) -> dict[str, dict[str, Any]]:
        return {
            "stats": self._stats.checkpoint_state(),
            "tactics": self._tactics.checkpoint_state(),
            "storyline": self._storyline.checkpoint_state(),
            "what_if": self._whatif.checkpoint_state(),
        }

    def restore(self, state: dict[str, dict[str, Any]]) -> None:
        self._stats.restore(state.get("stats", {}))
        self._tactics.restore(state.get("tactics", {}))
        self._storyline.restore(state.get("storyline", {}))
        self._whatif.restore(state.get("what_if", {}))

    def is_agent_dead(self, name: str) -> bool:
        return bool(self._agent_dead.get(name, False))

    def restart_tactics(self, state: dict[str, Any]) -> None:
        self._tactics = TacticsAgent(kill_after_sequence=self._kill_tactics_after_sequence)
        self._tactics.restore(state)
        self._agent_dead["tactics"] = False

    async def catch_up_tactics(self, match_id: str) -> None:
        last_seq = int(self._tactics.checkpoint_state().get("last_sequence", -1))
        missed = self._store.list_events_since_sequence(match_id, last_seq)
        for ev in missed:
            try:
                insights = await self._tactics.on_event(
                    match_id=match_id, event=ev, store=self._store, stats=self._stats
                )
                for ins in insights:
                    self._store.add_insight(match_id, ins)
            except AgentFailure:
                # If it dies again, keep it marked dead.
                self._agent_dead["tactics"] = True
                return

    async def on_event(self, match_id: str, event: MatchEvent) -> list[OverlayCue]:
        self._store.ingest_event(match_id, event)
        self._stats.ingest(event)

        insights: list[Insight] = []

        # Run storyline/tactics concurrently with a small latency budget.
        async def safe_call(name: str, coro):
            try:
                return await asyncio.wait_for(coro, timeout=1.5)
            except AgentFailure:
                self._agent_dead[name] = True
                return []
            except asyncio.TimeoutError:
                self._agent_dead[name] = True
                return []

        tactics_task = safe_call(
            "tactics",
            self._tactics.on_event(
                match_id=match_id, event=event, store=self._store, stats=self._stats
            ),
        )
        story_task = safe_call(
            "storyline", self._storyline.on_event(match_id=match_id, event=event, stats=self._stats)
        )
        tactics_ins, story_ins = await asyncio.gather(tactics_task, story_task)
        insights.extend(tactics_ins)
        insights.extend(story_ins)

        # What-if triggers on goals.
        if event.event_type == "goal":  # type: ignore[attr-defined]
            scoring_team = "home" if (event.team_id or "").endswith("_HOME") else "away"  # type: ignore[attr-defined]
            insights.append(
                await self._whatif.on_key_moment(
                    match_id=match_id,
                    store=self._store,
                    home_style=self._home_style,
                    away_style=self._away_style,
                    scoring_team=scoring_team,
                )
            )

        for ins in insights:
            self._store.add_insight(match_id, ins)

        # Graphics: if tactics is dead, fall back to templates.
        cues: list[OverlayCue] = []
        if self._agent_dead.get("tactics", False):
            cues.extend(
                await self._graphics.template_fallback(
                    match_id=match_id, event=event, stats=self._stats
                )
            )
        cues.extend(await self._graphics.build_cues(insights))

        # Compliance filter
        approved: list[OverlayCue] = []
        for cue in cues:
            decision = await self._compliance.validate(cue)
            if decision.ok:
                approved.append(personalize_cue(cue, self._profile))

        for cue in approved:
            self._store.add_overlay_cue(match_id, cue)

        return approved
