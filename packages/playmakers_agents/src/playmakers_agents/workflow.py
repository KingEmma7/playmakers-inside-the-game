from __future__ import annotations

import asyncio
import json
import math
import os
import re
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from time import perf_counter
from typing import Any, Literal, NamedTuple

from agent_framework import (
    Agent,
    BaseChatClient,
    CheckpointStorage,
    Executor,
    FileCheckpointStorage,
    MCPStreamableHTTPTool,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)
from playmakers_schema import models as event_models
from playmakers_schema.models import GoalEvent, MatchEvent
from playmakers_stats.engine import StatsEngine
from playmakers_stats.types import (
    ControlChaosResult,
    MomentumResult,
    PassDifficultyResult,
    PossessionResult,
    PressureIndexResult,
    XGResult,
)
from pydantic import BaseModel, Field, ValidationError

from playmakers_agents import contracts as contract_models
from playmakers_agents.checkpointing import FrameworkRecoveryStorage, RecoveryState, RecoveryStorage
from playmakers_agents.contracts import (
    AgentTraceEvent,
    ComplianceDecision,
    CueProvenance,
    Insight,
    OverlayCue,
    ViewerProfile,
)
from playmakers_agents.model_clients import create_playmakers_chat_client, is_live_client
from playmakers_agents.personalize import is_significant, personalize, significant_phrase
from playmakers_agents.players import player_name
from playmakers_agents.recap import (
    TEAM_NAMES,
    key_moments,
    localized_recap,
    recap_text,
    score,
    team_name,
)
from playmakers_agents.resilience import CircuitBreaker, KillSpec
from playmakers_agents.state_store import InMemoryMatchStore, MatchState, MatchStore
from playmakers_agents.what_if import WhatIfAgent

# Model calls are spent on moments a viewer would remember, plus a periodic tactical beat.
KEY_EVENT_TYPES = frozenset(
    {"shot", "goal", "foul", "card", "substitution", "kickoff", "period_start", "period_end"}
)
TACTICAL_BEAT_EVERY = 30
TOOL_EVENT_TYPES = frozenset({"shot", "goal"})


def key_moment(event: MatchEvent) -> bool:
    return event.event_type in KEY_EVENT_TYPES or event.sequence % TACTICAL_BEAT_EVERY == 0


def every_event(event: MatchEvent) -> bool:
    return True


# Seconds. Live models get room for a tool round-trip; the scripted kill stays the only "down".
LIVE_TIMEOUTS = {"agent": 8.0, "translation": 3.0, "what_if": 3.0}
MOCK_TIMEOUTS = {"agent": 4.0, "translation": 1.5, "what_if": 1.5}
TIMEOUT_ENV = {
    "agent": "PLAYMAKERS_AGENT_TIMEOUT_S",
    "translation": "PLAYMAKERS_TRANSLATION_TIMEOUT_S",
    "what_if": "PLAYMAKERS_WHATIF_TIMEOUT_S",
}
DEFAULT_STATS_MCP_URL = "http://127.0.0.1:8000/stats-mcp/"


def default_timeouts(live: bool) -> dict[str, float]:
    defaults = LIVE_TIMEOUTS if live else MOCK_TIMEOUTS
    resolved: dict[str, float] = {}
    for name, default in defaults.items():
        raw = os.getenv(TIMEOUT_ENV[name], "").strip()
        value = float(raw) if raw else default
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{TIMEOUT_ENV[name]} must be a positive number of seconds")
        resolved[name] = value
    return {
        "stats": 4.0,
        "tactics": resolved["agent"],
        "storyline": resolved["agent"],
        "graphics": 1.5,
        "translation": resolved["translation"],
        "what_if": resolved["what_if"],
    }


class StatsPacket(BaseModel):
    event: MatchEvent
    metrics: dict[str, float] = Field(default_factory=dict)
    evidence_event_ids: list[str] = Field(default_factory=list)
    metric_evidence: dict[str, list[str]] = Field(default_factory=dict)


class InsightPacket(BaseModel):
    stats: StatsPacket
    insight: Insight | None = None
    kind: Literal["tactics", "storyline"]
    error: str | None = None
    templated: bool = False


class ApprovedPacket(BaseModel):
    stats: StatsPacket
    insights: list[Insight]
    fallback: bool = False
    reviews: list[CueProvenance] = Field(default_factory=list)


class CuePacket(BaseModel):
    match_id: str
    cues: list[OverlayCue]


class StatQuery(NamedTuple):
    name: str
    result_type: type[BaseModel]
    applies: Callable[[MatchEvent], bool]
    arguments: Callable[[MatchEvent], dict[str, Any]]


def _at_clock(event: MatchEvent) -> dict[str, Any]:
    return {"match_clock_ms": event.clock_ms}


def _team_at_clock(event: MatchEvent) -> dict[str, Any]:
    return {"team_id": event.team_id, "match_clock_ms": event.clock_ms}


def _this_event(event: MatchEvent) -> dict[str, Any]:
    return {"event_id": event.event_id}


# Local engine methods and Stats MCP tools share these names.
STAT_QUERIES: tuple[StatQuery, ...] = (
    StatQuery("possession", PossessionResult, lambda _: True, _at_clock),
    StatQuery("momentum", MomentumResult, lambda _: True, _at_clock),
    StatQuery("pressure_index", PressureIndexResult, lambda e: bool(e.team_id), _team_at_clock),
    StatQuery("control_vs_chaos", ControlChaosResult, lambda e: bool(e.team_id), _team_at_clock),
    StatQuery(
        "pass_difficulty", PassDifficultyResult, lambda e: e.event_type == "pass", _this_event
    ),
    StatQuery("xg", XGResult, lambda e: e.event_type == "shot", _this_event),
)


def queries_for(event: MatchEvent) -> list[StatQuery]:
    return [query for query in STAT_QUERIES if query.applies(event)]


def compute_stats(engine: StatsEngine, event: MatchEvent) -> StatsPacket:
    """Same pure engine functions are used offline, by MCP, and by the verifier."""
    results = [
        getattr(engine, query.name)(**query.arguments(event)) for query in queries_for(event)
    ]
    metrics: dict[str, float] = {}
    metric_evidence: dict[str, list[str]] = {}
    evidence = {event.event_id}
    for result in results:
        evidence.update(result.evidence.event_ids)
        for key, value in result.model_dump().items():
            if isinstance(value, float):
                metrics[key] = value
                metric_evidence[key] = result.evidence.event_ids
    return StatsPacket(
        event=event,
        metrics=metrics,
        evidence_event_ids=sorted(evidence),
        metric_evidence=metric_evidence,
    )


def recap_stats(events: list[MatchEvent], full_time: MatchEvent) -> StatsPacket:
    home, away = score(events)
    goals = [e for e in events if isinstance(e, GoalEvent)]
    moments = key_moments(events)
    return StatsPacket(
        event=full_time,
        metrics={"home_goals": home, "away_goals": away},
        evidence_event_ids=list(
            dict.fromkeys(
                [*(m.event_id for m in moments), *(g.event_id for g in goals), full_time.event_id]
            )
        ),
        metric_evidence={
            "home_goals": [g.event_id for g in goals if g.scoring_team_id.endswith("_HOME")],
            "away_goals": [g.event_id for g in goals if not g.scoring_team_id.endswith("_HOME")],
        },
    )


def _number(value: float) -> str:
    return f"{round(value, 2) + 0.0:g}"


def _percent(value: float) -> str:
    return f"{round(value * 100, 2) + 0.0:g}%"


FOCUS = {
    "tactics": "Explain shape, pressure and passing.",
    "storyline": "Explain momentum and how the match story is developing.",
}


def describe_moment(event: MatchEvent) -> dict[str, Any]:
    """The event in words only: names instead of ids, no positions or measurements to misquote."""
    moment: dict[str, Any] = {}
    for key, value in event.model_dump(mode="json").items():
        if (
            key in {"event_id", "match_id", "schema_version", "labels"}
            or isinstance(value, (int, float, dict, list))
            and not isinstance(value, bool)
        ):
            continue
        if key.endswith("player_id"):
            moment[key.removesuffix("_id")] = player_name(value) or "a player"
        elif key.endswith("team_id"):
            moment[key.removesuffix("_id")] = team_name(value) if value else None
        else:
            moment[key] = value
    return moment


def quotable(metrics: dict[str, float]) -> dict[str, str]:
    """The exact strings Compliance accepts for each verified metric."""
    return {
        name: _percent(value) if "possession" in name or name.endswith("_rate") else _number(value)
        for name, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def model_insight(text: str, stats: StatsPacket, kind: str) -> dict[str, Any]:
    """Parse a model reply into an Insight payload.

    The model writes prose and names the metrics it used. Ids, clock and evidence it leaves out
    come from the handoff; anything it does supply is kept, so Compliance still checks it. Named
    metrics become their verified values, and unknown names stay invalid.
    """
    data = json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    data.setdefault("insight_id", f"{stats.event.event_id}:{kind}")
    data.setdefault("clock_ms", stats.event.clock_ms)
    data.setdefault("kind", kind)
    data.setdefault("evidence_event_ids", list(stats.evidence_event_ids))
    data.setdefault("metrics", list(stats.metrics))
    if isinstance(data.get("metrics"), list):
        data["metrics"] = {
            str(name): stats.metrics.get(str(name), math.nan) for name in data["metrics"]
        }
    return data


def _level(value: float, words: tuple[str, str, str]) -> str:
    return words[0] if value < 0.35 else words[1] if value < 0.65 else words[2]


def templated_insight(stats: StatsPacket, kind: Literal["tactics", "storyline"]) -> Insight:
    """Routine-event insight written from verified metrics only, so Compliance can pass it."""
    event, m = stats.event, stats.metrics
    team = team_name(event.team_id) if event.team_id else None
    if kind == "tactics":
        if "difficulty" in m and "pressure_index" in m:
            pass_kind = _level(m["difficulty"], ("Routine", "Testing", "Ambitious"))
            pressure = _level(m["pressure_index"], ("light", "moderate", "heavy"))
            headline = f"{pass_kind} pass under {pressure} pressure"
            detail = f"{team} keep the ball moving; this pass rated {_number(m['difficulty'])} for difficulty."
        elif "pressure_index" in m and "turnover_rate" in m:
            pressure = _level(m["pressure_index"], ("light", "steady", "heavy"))
            headline = f"{team} under {pressure} pressure"
            turnovers = _percent(m["turnover_rate"])
            detail = (
                f"They have given the ball away on {turnovers} of recent passes."
                if m["turnover_rate"]
                else f"No misplaced passes recently ({turnovers} turnovers)."
            )
        else:
            headline = "Both sides hold their shape"
            detail = f"The home side have {_percent(m['home_possession'])} of possession so far."
    else:
        momentum = m["home_momentum"]
        swing = (
            "with the home side"
            if momentum > 0.15
            else "with the visitors"
            if momentum < -0.15
            else "even"
        )
        headline = f"{team} on the ball" if team else "The match develops"
        detail = f"Momentum is {swing}, at {_number(momentum)}."
    return Insight(
        insight_id=f"{event.event_id}:{kind}",
        clock_ms=event.clock_ms,
        kind=kind,
        headline=headline,
        detail=detail,
        metrics=dict(m),
        evidence_event_ids=list(stats.evidence_event_ids),
    )


async def trace(
    ctx: WorkflowContext,
    agent: str,
    action: str,
    started: float,
    status: str = "ok",
    detail: str | None = None,
) -> None:
    await ctx.yield_output(
        AgentTraceEvent(
            agent=agent,
            action=action,
            detail=detail,
            latency_ms=(perf_counter() - started) * 1000,
            status=status,
        )
    )


class StatsExecutor(Executor):
    def __init__(self, director: Director) -> None:
        super().__init__(id="stats")
        self.director = director

    @handler
    async def handle(
        self, event: MatchEvent, ctx: WorkflowContext[StatsPacket, AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        engine = self.director.engines.setdefault(event.match_id, StatsEngine())
        engine.ingest(event)
        packet = compute_stats(engine, event)
        if self.director.mcp_tool:
            try:
                await asyncio.wait_for(
                    self.enrich_mcp(packet), timeout=self.director.timeouts["stats"]
                )
            except Exception:
                await trace(ctx, self.id, "fallback_on", started, "fallback")
        await trace(
            ctx,
            self.id,
            "computed",
            started,
            detail="Stats computed "
            + ("xG and possession" if event.event_type == "shot" else "possession and momentum"),
        )
        await ctx.send_message(packet)

    async def enrich_mcp(self, packet: StatsPacket) -> None:
        event = packet.event
        tool = self.director.mcp_tool
        assert tool is not None
        match_id = self.director.mcp_match_id(event.match_id)
        await tool.call_tool(
            "ingest_event",
            match_id=match_id,
            event={**event.model_dump(mode="json"), "match_id": match_id},
        )
        for query in queries_for(event):
            result = await tool.call_tool(query.name, match_id=match_id, **query.arguments(event))
            if not isinstance(result, str):
                raise ValueError("Expected structured MCP JSON")
            validated = query.result_type.model_validate_json(result)
            data = validated.model_dump()
            for key, value in data.items():
                if isinstance(value, float) and key in packet.metrics:
                    if not math.isclose(value, packet.metrics[key], abs_tol=1e-9):
                        raise ValueError("MCP stats differ from local evidence")
                    if validated.evidence.event_ids != packet.metric_evidence[key]:
                        raise ValueError("MCP evidence differs from local events")
                    packet.metrics[key] = value


class InsightExecutor(Executor):
    def __init__(
        self, kind: Literal["tactics", "storyline"], client: BaseChatClient, director: Director
    ) -> None:
        super().__init__(id=kind)
        self.kind = kind
        self.director = director
        self.breaker = CircuitBreaker()
        self.down = False
        self.agent_sequences: dict[str, int] = {}
        self.deadlines: dict[tuple[str, int], float] = {}
        self.instructions = (
            f"You are Playmakers's {kind} analyst for a synthetic fictional football match. "
            f"{FOCUS[kind]} Reply with one JSON object and nothing else, with three keys: "
            "headline (at most 8 words), detail (one sentence, at most 25 words) and metrics "
            "(a list of the keys of `metrics` that you mention). The system adds ids, clock and "
            "evidence. Describe `moment` in plain football language using the player and team "
            "names given. Use at most two numbers, each written exactly as in `quotable`. Never "
            "write IDs, clock times, distances, speeds, coordinates or any other number. Do not "
            "invent facts or names. If tools are available you may call one to confirm context; "
            "for MCP requests use the ids in `event`."
        )
        self.agent = Agent(
            client, name=kind, instructions=self.instructions, default_options={"max_tokens": 400}
        )
        self.tool_agent: Agent | None = None

    async def generate(
        self,
        stats: StatsPacket,
        reasons: list[str] | None = None,
        task: dict[str, Any] | None = None,
    ) -> InsightPacket:
        if self.down:
            return InsightPacket(stats=stats, kind=self.kind, error="agent_unavailable")
        key = (stats.event.match_id, stats.event.sequence, (task or {}).get("task", "insight"))
        deadline = self.deadlines.setdefault(
            key, perf_counter() + self.director.timeouts[self.kind]
        )
        try:
            return await asyncio.wait_for(
                self._generate_raw(stats, reasons)
                if task is None
                else self._ask(stats, reasons, task),
                timeout=max(0, deadline - perf_counter()),
            )
        except Exception:
            self.down = True
            self.breaker.fail(stats.event.sequence)
            return InsightPacket(stats=stats, kind=self.kind, error="agent_unavailable")

    async def _generate_raw(
        self, stats: StatsPacket, reasons: list[str] | None = None
    ) -> InsightPacket:
        return await self._ask(stats, reasons, None)

    async def _ask(
        self, stats: StatsPacket, reasons: list[str] | None, task: dict[str, Any] | None
    ) -> InsightPacket:
        event = stats.event
        prompt = json.dumps(
            {
                "event": {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "match_id": self.director.mcp_match_id(event.match_id),
                    "clock_ms": event.clock_ms,
                    "team_id": event.team_id,
                },
                "moment": describe_moment(event),
                "kind": self.kind,
                "metrics": stats.metrics,
                "quotable": quotable(stats.metrics),
                "evidence_event_ids": stats.evidence_event_ids,
                "correction": reasons or [],
                **(task or {}),
            }
        )
        agent = (
            self.tool_agent
            if self.tool_agent is not None and stats.event.event_type in TOOL_EVENT_TYPES
            else self.agent
        )
        try:
            response = await agent.run(prompt)
            insight = Insight.model_validate(model_insight(response.text, stats, self.kind))
            return InsightPacket(stats=stats, insight=insight, kind=self.kind)
        except (ValidationError, ValueError) as exc:
            return InsightPacket(stats=stats, kind=self.kind, error=type(exc).__name__)

    @handler
    async def handle(
        self, stats: StatsPacket, ctx: WorkflowContext[InsightPacket, AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        was_down = self.down
        if self.down and self.breaker.permits(stats.event.sequence):
            try:
                await self.director.recover(self, stats.event.match_id, stats.event.sequence)
                await trace(ctx, self.id, "restarted_from_checkpoint", started)
                await trace(ctx, self.id, "caught_up", started)
            except Exception:
                self.down = True
                self.breaker.fail(stats.event.sequence)
        if not self.down and not self.director.model_events(stats.event):
            self.agent_sequences[stats.event.match_id] = stats.event.sequence
            await trace(
                ctx,
                self.id,
                "templated",
                started,
                detail=f"{self.kind.title()} used a template caption",
            )
            await ctx.send_message(
                InsightPacket(
                    stats=stats,
                    insight=templated_insight(stats, self.kind),
                    kind=self.kind,
                    templated=True,
                )
            )
            return
        packet = await self.generate(stats)
        if self.down:
            if not was_down:
                await trace(ctx, self.id, "agent_down", started, "error")
            await trace(ctx, self.id, "fallback_on", started, "fallback")
        elif packet.insight:
            self.agent_sequences[stats.event.match_id] = stats.event.sequence
        await trace(
            ctx,
            self.id,
            "insight",
            started,
            "ok" if packet.insight else "rejected",
            detail=f"{self.kind.title()} drafted a caption" if packet.insight else None,
        )
        await ctx.send_message(packet)


class ComplianceExecutor(Executor):
    def __init__(self, store: MatchStore, writers: list[InsightExecutor]) -> None:
        super().__init__(id="compliance")
        self.store = store
        self.writers = {writer.kind: writer for writer in writers}

    def validate(self, packet: InsightPacket) -> ComplianceDecision:
        insight, event = packet.insight, packet.stats.event
        reasons: list[str] = []
        if insight is None:
            return ComplianceDecision(ok=False, reasons=[packet.error or "Missing insight"])
        if insight.kind != packet.kind or insight.clock_ms != event.clock_ms:
            reasons.append("Insight kind or clock differs from handoff")
        if not insight.evidence_event_ids:
            reasons.append("Missing evidence")
        # StatsExecutor and kill-recover both build this packet from the stored event prefix.
        expected = packet.stats
        cited = set(insight.evidence_event_ids)
        if not cited.issubset(set(expected.evidence_event_ids)) or event.event_id not in cited:
            reasons.append("Evidence includes unknown/future events or omits current event")
        verified: list[float] = []
        for key, value in insight.metrics.items():
            if (
                key not in expected.metrics
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not math.isclose(value, expected.metrics[key], rel_tol=0, abs_tol=1e-9)
            ):
                reasons.append(f"Ungrounded metric: {key}")
            elif not set(expected.metric_evidence[key]).issubset(cited):
                reasons.append(f"Missing metric evidence: {key}")
            else:
                verified.append(float(value))
        # Numeric prose is allowed only as a metric value (or percent), rounded to two decimals.
        prose = re.sub(r"\b\d{1,3}:[0-5]\d\b", "", insight.headline + " " + insight.detail)
        prose = re.sub(r"(?i)(?:jersey|shirt|number|no\.)\s*#?\s*(?:[1-9]\d?)(?![\d.])", "", prose)
        # A hyphen right after a digit joins a score ("3-3"); it is not a minus sign.
        numeric_prose = re.findall(r"((?<![\d.])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(%?)", prose)
        for number, percent in numeric_prose:
            value = float(number)
            allowed = [round(v * (100 if percent else 1), 2) for v in verified]
            if value not in allowed:
                reasons.append("Ungrounded number in prose")
        return ComplianceDecision(
            ok=not reasons,
            reasons=reasons,
            numbers_checked=len(insight.metrics) + len(numeric_prose),
        )

    @handler
    async def handle(
        self, packets: list[InsightPacket], ctx: WorkflowContext[ApprovedPacket, AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        approved: list[Insight] = []
        reviews: list[CueProvenance] = []
        fallback = False
        numbers_checked = 0
        for packet in packets:
            event = packet.stats.event
            if is_significant(event):
                events = self.store.get_or_create(event.match_id).events
                home, away = score(events)
                moment = significant_phrase(event, "en", home, away)
                goals = [e for e in events if isinstance(e, GoalEvent)]
                packet.stats.metrics.update(
                    home_goals=home, away_goals=away, minute=event.clock_ms // 60_000 + 1
                )
                for key in ("home_goals", "away_goals", "minute"):
                    packet.stats.metric_evidence[key] = (
                        [event.event_id]
                        if key == "minute"
                        else [
                            g.event_id
                            for g in goals
                            if g.scoring_team_id.endswith("_HOME") == (key == "home_goals")
                        ]
                    )
                packet.stats.evidence_event_ids = list(
                    dict.fromkeys([*packet.stats.evidence_event_ids, *(g.event_id for g in goals)])
                )
                packet.insight = Insight(
                    insight_id=f"{event.event_id}:{packet.kind}",
                    clock_ms=event.clock_ms,
                    kind=packet.kind,
                    headline=moment[0],
                    detail=moment[1],
                    metrics=dict(packet.stats.metrics),
                    evidence_event_ids=list(packet.stats.evidence_event_ids),
                )
                packet.templated = True
            decision = self.validate(packet)
            numbers_checked += decision.numbers_checked
            attempts = 1
            reasons = list(decision.reasons)
            if not decision.ok:
                await trace(ctx, self.id, "rejected", started, "rejected")
            for attempt in range(2):
                if decision.ok or packet.error == "agent_unavailable" or packet.templated:
                    break
                await trace(ctx, self.id, f"retry_{attempt + 1}", started, "retry")
                retry_started = perf_counter()
                packet = await self.writers[packet.kind].generate(packet.stats, decision.reasons)
                await trace(
                    ctx,
                    packet.kind,
                    "retry_insight",
                    retry_started,
                    "ok" if packet.insight else "rejected",
                )
                decision = self.validate(packet)
                numbers_checked += decision.numbers_checked
                attempts += 1
                reasons += decision.reasons
            if decision.ok and packet.insight:
                approved.append(packet.insight)
                self.store.add_insight(packet.stats.event.match_id, packet.insight)
                reviews.append(
                    CueProvenance(
                        agent=packet.kind,
                        source="template" if packet.templated else "agent",
                        compliance="verified",
                        attempts=attempts,
                        reasons=reasons,
                        metrics=packet.insight.metrics,
                        metric_evidence={
                            key: packet.stats.metric_evidence[key]
                            for key in packet.insight.metrics
                            if key in packet.stats.metric_evidence
                        },
                        insight_headline=packet.insight.headline,
                    )
                )
            else:
                fallback = True
                approved.append(
                    Insight(
                        insight_id=f"{packet.stats.event.event_id}:{packet.kind}:template",
                        clock_ms=packet.stats.event.clock_ms,
                        kind=packet.kind,
                        headline="Match update",
                        detail="The synthetic match continues.",
                        evidence_event_ids=[packet.stats.event.event_id],
                    )
                )
                reviews.append(
                    CueProvenance(
                        agent=packet.kind,
                        source="template",
                        compliance="template_fallback",
                        attempts=attempts,
                        reasons=reasons or [packet.error or "No approved insight"],
                    )
                )
        await trace(
            ctx,
            self.id,
            "verified" if not fallback else "template",
            started,
            "ok" if not fallback else "fallback",
            detail=f"Compliance checked {numbers_checked} numbers",
        )
        await ctx.send_message(
            ApprovedPacket(
                stats=packets[0].stats, insights=approved, fallback=fallback, reviews=reviews
            )
        )


class GraphicsExecutor(Executor):
    def __init__(self, timeout: float = 1.5) -> None:
        super().__init__(id="graphics")
        self.timeout = timeout

    @handler
    async def handle(
        self, packet: ApprovedPacket, ctx: WorkflowContext[CuePacket, AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        try:
            cues = await asyncio.wait_for(self.render(packet), timeout=self.timeout)
        except Exception:
            cues = [
                OverlayCue(
                    cue_id=f"{packet.stats.event.event_id}:graphics:template",
                    clock_ms=packet.stats.event.clock_ms,
                    template="template_fallback",
                    payload={
                        "headline": "Match update",
                        "detail": "The synthetic match continues.",
                        "metrics": {},
                    },
                    evidence_event_ids=[packet.stats.event.event_id],
                    provenance=CueProvenance(
                        agent="graphics",
                        source="template",
                        compliance="template_fallback",
                        reasons=["Graphics render failed or timed out"],
                    ),
                )
            ]
            await trace(ctx, self.id, "fallback_on", started, "fallback")
        await trace(ctx, self.id, "schema_validated", started, detail="Graphics validated the cues")
        await ctx.send_message(CuePacket(match_id=packet.stats.event.match_id, cues=cues))

    async def render(self, packet: ApprovedPacket) -> list[OverlayCue]:
        return [
            OverlayCue.model_validate(
                {
                    "cue_id": insight.insight_id,
                    "clock_ms": insight.clock_ms,
                    "template": "template_fallback"
                    if insight.insight_id.endswith(":template")
                    else insight.kind,
                    "priority": 85 if is_significant(packet.stats.event) else 0,
                    "payload": {
                        **(
                            {"moment": packet.stats.event.event_type, "hold_ms": 60_000}
                            if is_significant(packet.stats.event)
                            else {}
                        ),
                        "headline": insight.headline,
                        "detail": insight.detail,
                        "metrics": insight.metrics,
                    },
                    "evidence_event_ids": insight.evidence_event_ids,
                    "provenance": packet.reviews[index] if index < len(packet.reviews) else None,
                }
            )
            for index, insight in enumerate(packet.insights)
        ]


class AudienceExecutor(Executor):
    def __init__(
        self,
        profiles: list[ViewerProfile],
        store: MatchStore,
        client: BaseChatClient,
        timeout: float = 1.5,
    ) -> None:
        super().__init__(id="audience")
        self.profiles, self.store, self.client = profiles, store, client
        self.timeout = timeout
        self.previous_lines: dict[int, tuple[str, str]] = {}

    @handler
    async def handle(
        self, packet: CuePacket, ctx: WorkflowContext[Any, OverlayCue | AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        for index, profile in enumerate(self.profiles):
            for cue in packet.cues:
                event = self.store.get_or_create(packet.match_id).events[-1]
                prior_id, prior_line = self.previous_lines.get(index, ("", ""))
                # Both writers describe the same event with the same fan caption.
                previous = prior_line if prior_id != event.event_id else ""
                shaped = await personalize(
                    cue, profile, event, self.client, index, self.timeout, previous
                )
                if profile.persona == "casual":
                    if prior_id == event.event_id:
                        shaped.payload["headline"] = prior_line
                    else:
                        self.previous_lines[index] = (event.event_id, shaped.payload["headline"])
                # Verify the localized prose too, using the already approved metric evidence.
                if shaped.provenance and shaped.provenance.compliance == "verified":
                    metrics = shaped.payload.get("metrics", {})
                    stats = StatsPacket(
                        event=event,
                        metrics=metrics,
                        evidence_event_ids=shaped.evidence_event_ids,
                        metric_evidence=shaped.provenance.metric_evidence,
                    )
                    insight = Insight(
                        insight_id=shaped.cue_id,
                        kind=shaped.provenance.agent,
                        clock_ms=shaped.clock_ms,
                        headline=shaped.payload["headline"],
                        detail=shaped.payload["detail"],
                        metrics=metrics,
                        evidence_event_ids=shaped.evidence_event_ids,
                    )
                    decision = ComplianceExecutor(self.store, []).validate(
                        InsightPacket(stats=stats, insight=insight, kind=insight.kind)
                    )
                    if not decision.ok:
                        raise ValueError(f"Unverified audience caption: {decision.reasons}")
                self.store.add_overlay_cue(packet.match_id, shaped)
                await ctx.yield_output(shaped)
        await trace(
            ctx,
            self.id,
            "fan_out",
            started,
            detail="Audience made "
            + " and ".join(
                dict.fromkeys(
                    {"en": "English", "es": "Spanish", "fr": "French"}[p.language]
                    for p in self.profiles
                )
            )
            + " versions",
        )


class Director:
    """Real Agent Framework fan-out/fan-in workflow; model access remains pluggable."""

    def __init__(
        self,
        *,
        profiles: list[ViewerProfile] | None = None,
        client: BaseChatClient | None = None,
        store: MatchStore | None = None,
        checkpoint_storage: CheckpointStorage | None = None,
        checkpoint_path: str | None = None,
        stats_mcp_url: str | None = None,
        recovery_storage: RecoveryStorage | None = None,
        kill: str | None = None,
        whatif_rollouts: int = 200,
        whatif_pool: ProcessPoolExecutor | None = None,
        seed: int = 0,
        timeouts: dict[str, float] | None = None,
        model_events: Callable[[MatchEvent], bool] = key_moment,
    ) -> None:
        self.store = store or InMemoryMatchStore()
        self.model_events = model_events
        self.kill = KillSpec.parse(kill)
        self.killed = False
        self.client = client or create_playmakers_chat_client()
        self.timeouts = {**default_timeouts(is_live_client(self.client)), **(timeouts or {})}
        self._temporary_checkpoints = None
        if checkpoint_storage is None and checkpoint_path is None:
            self._temporary_checkpoints = tempfile.TemporaryDirectory(prefix="playmakers-")
            checkpoint_path = self._temporary_checkpoints.name
        self.engines: dict[str, StatsEngine] = {}
        self.what_if = WhatIfAgent(
            self.client,
            whatif_rollouts,
            seed,
            pool=whatif_pool,
            explain_timeout=self.timeouts["what_if"],
        )
        self.profiles = profiles or [ViewerProfile()]
        self.last_traces: list[AgentTraceEvent] = []
        self._lock = asyncio.Lock()
        self.mcp_tool: MCPStreamableHTTPTool | None = None
        # The Stats MCP server is shared by every session in the API process, and two sessions
        # can replay the same seed, so each Director keeps its own match state there.
        self._mcp_session = uuid.uuid4().hex[:12]
        self.stats_mcp_url = stats_mcp_url
        if is_live_client(self.client):
            # The API mounts Stats MCP in-process; a standalone server needs STATS_MCP_URL.
            self.stats_mcp_url = stats_mcp_url or os.getenv("STATS_MCP_URL", DEFAULT_STATS_MCP_URL)
        if checkpoint_path:
            allowed = [
                f"playmakers_agents.workflow:{name}"
                for name in ("StatsPacket", "InsightPacket", "ApprovedPacket", "CuePacket")
            ]
            for module in (event_models, contract_models):
                allowed.extend(
                    f"{module.__name__}:{name}"
                    for name, value in vars(module).items()
                    if isinstance(value, type)
                    and issubclass(value, BaseModel)
                    and value.__module__ == module.__name__
                )
            checkpoint_storage = FileCheckpointStorage(
                checkpoint_path, allowed_checkpoint_types=allowed
            )
        self.checkpoint_storage = checkpoint_storage
        self.recovery_storage = recovery_storage or FrameworkRecoveryStorage(checkpoint_storage)
        stats = StatsExecutor(self)
        self.writers = [
            InsightExecutor("tactics", self.client, self),
            InsightExecutor("storyline", self.client, self),
        ]
        self.compliance = ComplianceExecutor(self.store, self.writers)
        self.graphics = graphics = GraphicsExecutor(self.timeouts["graphics"])
        audience = AudienceExecutor(
            self.profiles, self.store, self.client, self.timeouts["translation"]
        )
        self.workflow = (
            WorkflowBuilder(
                name="playmakers-director-v1",
                start_executor=stats,
                checkpoint_storage=checkpoint_storage,
            )
            .add_fan_out_edges(stats, self.writers)
            .add_fan_in_edges(self.writers, self.compliance)
            .add_edge(self.compliance, graphics)
            .add_edge(graphics, audience)
            .build()
        )

    async def __aenter__(self) -> Director:
        if self.stats_mcp_url:
            self.mcp_tool = MCPStreamableHTTPTool(
                name="playmakers_stats",
                url=self.stats_mcp_url,
                load_prompts=False,
                parse_tool_results=lambda result: json.dumps(result.structuredContent),
            )
            await self.mcp_tool.__aenter__()
            for writer in self.writers:
                writer.tool_agent = self._tool_agent(writer)
        return self

    def _tool_agent(self, writer: InsightExecutor) -> Agent | None:
        # Live agents may request the same deterministic Stats tools, but only on shots and goals.
        if self.mcp_tool is None:
            return None
        return Agent(
            self.client,
            name=writer.kind,
            instructions=writer.instructions,
            tools=[f for f in self.mcp_tool.functions if f.name != "ingest_event"],
            default_options={"max_tokens": 400},
        )

    async def __aexit__(self, *args: Any) -> None:
        try:
            if self.mcp_tool:
                await self.mcp_tool.__aexit__(*args)
        finally:
            await self.what_if.close()
            if self._temporary_checkpoints:
                self._temporary_checkpoints.cleanup()

    def mcp_match_id(self, match_id: str) -> str:
        return f"{match_id}~{self._mcp_session}"

    async def restore(self, match_id: str) -> bool:
        """Restore a fresh Director's shared state before consuming the next event."""
        saved = await self.recovery_storage.load(match_id)
        if saved is None:
            return False
        if self.store.get_or_create(match_id).events:
            raise ValueError("Restore requires an empty match store")
        engine = StatsEngine()
        for event in saved.match.events:
            self.store.ingest_event(match_id, event)
            engine.ingest(event)
        self.engines[match_id] = engine
        for writer in self.writers:
            writer.agent_sequences[match_id] = saved.agent_sequences.get(writer.kind, -1)
        return True

    async def recover(self, writer: InsightExecutor, match_id: str, current_sequence: int) -> None:
        saved = await self.recovery_storage.load(match_id)
        last = saved.agent_sequences.get(writer.kind, -1) if saved else -1
        writer.agent = Agent(
            self.client,
            name=writer.kind,
            instructions=writer.instructions,
            default_options={"max_tokens": 400},
        )
        writer.tool_agent = self._tool_agent(writer)
        engine = StatsEngine()
        for event in self.store.get_or_create(match_id).events:
            if event.sequence >= current_sequence:
                break
            engine.ingest(event)
            if event.sequence > last and self.model_events(event):
                packet = await asyncio.wait_for(
                    writer._generate_raw(compute_stats(engine, event)),
                    timeout=self.timeouts[writer.kind],
                )
                if not self.compliance.validate(packet).ok:
                    raise ValueError("Replay failed compliance")
                writer.agent_sequences[match_id] = event.sequence
        writer.down = False
        writer.breaker.reset()

    async def full_time_recap(self, event: MatchEvent) -> list[OverlayCue]:
        started = perf_counter()
        events = self.store.get_or_create(event.match_id).events
        stats = recap_stats(events, event)
        home, away = int(stats.metrics["home_goals"]), int(stats.metrics["away_goals"])
        moments = key_moments(events)
        task = {
            "task": "recap",
            "instructions": "Write a full-time recap headline and one-sentence detail. "
            "Use only the supplied score and team names; cite all evidence_event_ids. "
            "The only numbers you may write are the two goal totals: no minutes or times.",
            "teams": TEAM_NAMES,
            "moments": [m.model_dump() for m in moments],
        }
        writer = self.writers[1]
        packet = await writer.generate(stats, task=task)
        decision = self.compliance.validate(packet)
        attempts, reasons = 1, list(decision.reasons)
        while not decision.ok and attempts < 3 and packet.error != "agent_unavailable":
            packet = await writer.generate(stats, decision.reasons, task)
            decision = self.compliance.validate(packet)
            attempts += 1
            reasons += decision.reasons
        verified = decision.ok and packet.insight is not None
        headline, detail = recap_text(home, away, "en", "analyst")
        base = (
            packet.insight
            if verified and packet.insight
            else Insight(
                insight_id=f"{event.event_id}:recap:template",
                clock_ms=event.clock_ms,
                kind="storyline",
                headline=headline,
                detail=detail,
                metrics=stats.metrics,
                evidence_event_ids=stats.evidence_event_ids,
            )
        )
        cues: list[OverlayCue] = []
        for index, profile in enumerate(self.profiles):
            insight = localized_recap(base, home, away, profile.language, profile.persona)
            review = self.compliance.validate(
                InsightPacket(stats=stats, insight=insight, kind="storyline")
            )
            if not review.ok:
                insight = base
                review = self.compliance.validate(
                    InsightPacket(stats=stats, insight=insight, kind="storyline")
                )
            if not review.ok:
                continue
            cue = OverlayCue(
                cue_id=f"{event.event_id}:recap:viewer{index}",
                clock_ms=event.clock_ms,
                template="recap",
                priority=90,
                duration_ms=30_000,
                layer="full_screen",
                payload={
                    "headline": insight.headline,
                    "detail": insight.detail,
                    "home_goals": home,
                    "away_goals": away,
                    "moments": [m.model_dump() for m in moments],
                },
                evidence_event_ids=insight.evidence_event_ids,
                persona=profile.persona,
                language=profile.language,
                provenance=CueProvenance(
                    agent="storyline",
                    source="agent" if verified else "template",
                    compliance="verified" if verified else "template_fallback",
                    attempts=attempts,
                    reasons=reasons,
                    metrics=stats.metrics,
                    metric_evidence=stats.metric_evidence,
                ),
            )
            self.store.add_overlay_cue(event.match_id, cue)
            cues.append(cue)
        self.last_traces += [
            AgentTraceEvent(
                agent="storyline",
                action="recap",
                latency_ms=(perf_counter() - started) * 1000,
                status="ok" if verified else "fallback",
            ),
            AgentTraceEvent(
                agent="compliance",
                action="recap_verified" if verified else "recap_template",
                latency_ms=(perf_counter() - started) * 1000,
                status="ok" if verified else "fallback",
            ),
        ]
        return cues

    async def on_event(
        self,
        event: MatchEvent,
        publish: Callable[[list[OverlayCue], list[AgentTraceEvent]], Awaitable[None]] | None = None,
    ) -> list[OverlayCue]:
        if self.stats_mcp_url and not self.mcp_tool:
            raise RuntimeError("Use async with Director() to connect MCP")
        async with self._lock:
            self.store.ingest_event(event.match_id, event)
            injected = False
            if self.kill and not self.killed and event.clock_ms >= self.kill.minute * 60000:
                writer = self.writers[0]
                writer.down = True
                writer.breaker.fail(event.sequence)
                self.killed = injected = True
            workflow_started = perf_counter()
            result = await self.workflow.run(event)
            outputs = result.get_outputs()
            self.last_traces = [row for row in outputs if isinstance(row, AgentTraceEvent)]
            self.last_traces.append(
                AgentTraceEvent(
                    agent="director",
                    action="coordinated",
                    detail="Director coordinated the cue",
                    latency_ms=(perf_counter() - workflow_started) * 1000,
                )
            )
            if injected:
                self.last_traces.insert(
                    0,
                    AgentTraceEvent(
                        agent="tactics", action="agent_down", latency_ms=0, status="error"
                    ),
                )
            cues = [row for row in outputs if isinstance(row, OverlayCue)]
            if publish:
                await publish(cues.copy(), self.last_traces.copy())
            started = perf_counter()
            extra = await self.what_if.evaluate(self.store.get_or_create(event.match_id).events)
            if extra:
                for index, profile in enumerate(self.profiles):
                    shaped = await personalize(
                        extra, profile, event, self.client, index, self.timeouts["translation"]
                    )
                    cues.append(shaped)
                    self.store.add_overlay_cue(event.match_id, shaped)
                self.last_traces.append(
                    AgentTraceEvent(
                        agent="what_if",
                        action="rollouts_verified",
                        detail=f"What-If ran {extra.payload['metrics']['rollouts']} simulations",
                        latency_ms=(perf_counter() - started) * 1000,
                    )
                )
            if event.event_type == "period_end" and event.period == 2:
                cues += await self.full_time_recap(event)
            state = self.store.get_or_create(event.match_id)
            if (
                len(state.events) == 1
                or event.sequence % 25 == 0
                or injected
                or any(
                    t.action in ("restarted_from_checkpoint", "caught_up") for t in self.last_traces
                )
                or (event.event_type == "period_end" and event.period == 2)
            ):
                await self.recovery_storage.save(
                    RecoveryState(
                        match=MatchState(
                            match_id=event.match_id,
                            events=state.events,
                            last_sequence=state.last_sequence,
                        ),
                        agent_sequences={
                            w.kind: w.agent_sequences.get(event.match_id, -1) for w in self.writers
                        },
                    )
                )
            return cues
