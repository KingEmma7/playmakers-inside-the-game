from __future__ import annotations

import asyncio
import json
import math
import os
import re
from time import perf_counter
from typing import Any, Literal

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
from gallery_schema import models as event_models
from gallery_schema.models import MatchEvent
from gallery_stats.engine import StatsEngine
from gallery_stats.types import (
    ControlChaosResult,
    MomentumResult,
    PassDifficultyResult,
    PossessionResult,
    PressureIndexResult,
    XGResult,
)
from pydantic import BaseModel, Field, ValidationError

from gallery_agents import contracts as contract_models
from gallery_agents.contracts import (
    AgentTraceEvent,
    ComplianceDecision,
    Insight,
    OverlayCue,
    ViewerProfile,
)
from gallery_agents.model_clients import DeterministicMockChatClient, create_gallery_chat_client
from gallery_agents.state_store import InMemoryMatchStore, MatchStore


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


class ApprovedPacket(BaseModel):
    stats: StatsPacket
    insights: list[Insight]
    fallback: bool = False


class CuePacket(BaseModel):
    match_id: str
    cues: list[OverlayCue]


def compute_stats(engine: StatsEngine, event: MatchEvent) -> StatsPacket:
    """Same pure engine functions are used offline, by MCP, and by the verifier."""
    results = [
        engine.possession(match_clock_ms=event.clock_ms),
        engine.momentum(match_clock_ms=event.clock_ms),
    ]
    if event.team_id:
        results.extend(
            [
                engine.pressure_index(team_id=event.team_id, match_clock_ms=event.clock_ms),
                engine.control_vs_chaos(team_id=event.team_id, match_clock_ms=event.clock_ms),
            ]
        )
    if event.event_type == "pass":
        results.append(engine.pass_difficulty(event_id=event.event_id))
    if event.event_type == "shot":
        results.append(engine.xg(event_id=event.event_id))
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


async def trace(
    ctx: WorkflowContext, agent: str, action: str, started: float, status: str = "ok"
) -> None:
    await ctx.yield_output(
        AgentTraceEvent(
            agent=agent, action=action, latency_ms=(perf_counter() - started) * 1000, status=status
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
        if tool := self.director.mcp_tool:
            await tool.call_tool(
                "ingest_event", match_id=event.match_id, event=event.model_dump(mode="json")
            )
            queries: list[tuple[str, dict[str, Any]]] = [
                ("possession", {"match_clock_ms": event.clock_ms}),
                ("momentum", {"match_clock_ms": event.clock_ms}),
            ]
            if event.team_id:
                for name in ("pressure_index", "control_vs_chaos"):
                    queries.append(
                        (name, {"team_id": event.team_id, "match_clock_ms": event.clock_ms})
                    )
            if event.event_type in ("pass", "shot"):
                queries.append(
                    (
                        "pass_difficulty" if event.event_type == "pass" else "xg",
                        {"event_id": event.event_id},
                    )
                )
            for name, arguments in queries:
                result = await tool.call_tool(name, match_id=event.match_id, **arguments)
                if not isinstance(result, str):
                    raise ValueError("Expected structured MCP JSON")
                result_types = {
                    "possession": PossessionResult,
                    "momentum": MomentumResult,
                    "pressure_index": PressureIndexResult,
                    "control_vs_chaos": ControlChaosResult,
                    "pass_difficulty": PassDifficultyResult,
                    "xg": XGResult,
                }
                validated = result_types[name].model_validate_json(result)
                data = validated.model_dump()
                for key, value in data.items():
                    if isinstance(value, float) and key in packet.metrics:
                        if not math.isclose(value, packet.metrics[key], abs_tol=1e-9):
                            raise ValueError("MCP stats differ from local evidence")
                        if validated.evidence.event_ids != packet.metric_evidence[key]:
                            raise ValueError("MCP evidence differs from local events")
                        packet.metrics[key] = value
        await trace(ctx, self.id, "computed", started)
        await ctx.send_message(packet)


class InsightExecutor(Executor):
    def __init__(self, kind: Literal["tactics", "storyline"], client: BaseChatClient) -> None:
        super().__init__(id=kind)
        self.kind = kind
        self.instructions = (
            f"You are Gallery's {kind} analyst for a synthetic fictional football match. "
            "Return only an Insight JSON object with insight_id, clock_ms, kind, headline, detail, "
            "metrics, evidence_event_ids. Cite supplied event IDs. Copy numeric metrics exactly; "
            "every number in prose must match a metric. Do not invent facts or names. "
            "When tools are available, call possession or pressure_index to verify context before answering. "
            "For MCP requests use event.match_id, event.event_id, event.clock_ms and event.team_id."
        )
        self.agent = Agent(
            client, name=kind, instructions=self.instructions, default_options={"max_tokens": 800}
        )

    async def generate(self, stats: StatsPacket, reasons: list[str] | None = None) -> InsightPacket:
        prompt = json.dumps(
            {
                "event": stats.event.model_dump(mode="json"),
                "kind": self.kind,
                "metrics": stats.metrics,
                "evidence_event_ids": stats.evidence_event_ids,
                "correction": reasons or [],
            }
        )
        try:
            response = await self.agent.run(prompt)
            insight = Insight.model_validate_json(response.text)
            return InsightPacket(stats=stats, insight=insight, kind=self.kind)
        except (ValidationError, ValueError) as exc:
            return InsightPacket(stats=stats, kind=self.kind, error=type(exc).__name__)

    @handler
    async def handle(
        self, stats: StatsPacket, ctx: WorkflowContext[InsightPacket, AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        packet = await self.generate(stats)
        await trace(ctx, self.id, "insight", started, "ok" if packet.insight else "rejected")
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
        engine = StatsEngine()
        for row in self.store.get_or_create(event.match_id).events:
            if row.sequence <= event.sequence:
                engine.ingest(row)
        expected = compute_stats(engine, event)
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
        for number, percent in re.findall(
            r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(%?)", insight.headline + " " + insight.detail
        ):
            value = float(number)
            allowed = [round(v * (100 if percent else 1), 2) for v in verified]
            if value not in allowed:
                reasons.append("Ungrounded number in prose")
        return ComplianceDecision(ok=not reasons, reasons=reasons)

    @handler
    async def handle(
        self, packets: list[InsightPacket], ctx: WorkflowContext[ApprovedPacket, AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        approved: list[Insight] = []
        fallback = False
        for packet in packets:
            decision = self.validate(packet)
            if not decision.ok:
                await trace(ctx, self.id, "rejected", started, "rejected")
            for attempt in range(2):
                if decision.ok:
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
            if decision.ok and packet.insight:
                approved.append(packet.insight)
                self.store.add_insight(packet.stats.event.match_id, packet.insight)
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
        await trace(
            ctx,
            self.id,
            "verified" if not fallback else "template",
            started,
            "ok" if not fallback else "fallback",
        )
        await ctx.send_message(
            ApprovedPacket(stats=packets[0].stats, insights=approved, fallback=fallback)
        )


class GraphicsExecutor(Executor):
    def __init__(self) -> None:
        super().__init__(id="graphics")

    @handler
    async def handle(
        self, packet: ApprovedPacket, ctx: WorkflowContext[CuePacket, AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        cues = [
            OverlayCue.model_validate(
                {
                    "cue_id": insight.insight_id,
                    "clock_ms": insight.clock_ms,
                    "template": "template_fallback"
                    if insight.insight_id.endswith(":template")
                    else insight.kind,
                    "payload": {
                        "headline": insight.headline,
                        "detail": insight.detail,
                        "metrics": insight.metrics,
                    },
                    "evidence_event_ids": insight.evidence_event_ids,
                }
            )
            for insight in packet.insights
        ]
        await trace(ctx, self.id, "schema_validated", started)
        await ctx.send_message(CuePacket(match_id=packet.stats.event.match_id, cues=cues))


class AudienceExecutor(Executor):
    def __init__(self, profiles: list[ViewerProfile], store: MatchStore) -> None:
        super().__init__(id="audience")
        self.profiles, self.store = profiles, store

    @handler
    async def handle(
        self, packet: CuePacket, ctx: WorkflowContext[Any, OverlayCue | AgentTraceEvent]
    ) -> None:
        started = perf_counter()
        for index, profile in enumerate(self.profiles):
            for cue in packet.cues:
                shaped = cue.model_copy(
                    update={
                        "cue_id": f"{cue.cue_id}:viewer{index}",
                        "persona": profile.persona,
                        "language": profile.language,
                    }
                )
                self.store.add_overlay_cue(packet.match_id, shaped)
                await ctx.yield_output(shaped)
        await trace(ctx, self.id, "fan_out", started)


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
    ) -> None:
        self.store = store or InMemoryMatchStore()
        self.client = client or create_gallery_chat_client()
        self.engines: dict[str, StatsEngine] = {}
        self.last_traces: list[AgentTraceEvent] = []
        self._lock = asyncio.Lock()
        self.mcp_tool: MCPStreamableHTTPTool | None = None
        self.stats_mcp_url = stats_mcp_url
        if not isinstance(self.client, DeterministicMockChatClient):
            self.stats_mcp_url = stats_mcp_url or os.getenv(
                "STATS_MCP_URL", "http://127.0.0.1:8765/mcp"
            )
        if checkpoint_path:
            allowed = [
                f"gallery_agents.workflow:{name}"
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
        stats = StatsExecutor(self)
        self.writers = [
            InsightExecutor("tactics", self.client),
            InsightExecutor("storyline", self.client),
        ]
        self.compliance = ComplianceExecutor(self.store, self.writers)
        graphics = GraphicsExecutor()
        audience = AudienceExecutor(profiles or [ViewerProfile()], self.store)
        self.workflow = (
            WorkflowBuilder(
                name="gallery-director-v1",
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
                name="gallery_stats",
                url=self.stats_mcp_url,
                load_prompts=False,
                parse_tool_results=lambda result: json.dumps(result.structuredContent),
            )
            await self.mcp_tool.__aenter__()
            for writer in self.writers:
                # Live agents can request the very same deterministic tools; Stats also calls them explicitly.
                writer.agent = Agent(
                    self.client,
                    name=writer.kind,
                    instructions=writer.instructions,
                    tools=[
                        function
                        for function in self.mcp_tool.functions
                        if function.name != "ingest_event"
                    ],
                    default_options={"max_tokens": 800},
                )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self.mcp_tool:
            await self.mcp_tool.__aexit__(*args)

    async def on_event(self, event: MatchEvent) -> list[OverlayCue]:
        if self.stats_mcp_url and not self.mcp_tool:
            raise RuntimeError("Use async with Director() to connect MCP")
        async with self._lock:
            self.store.ingest_event(event.match_id, event)
            result = await self.workflow.run(event)
            outputs = result.get_outputs()
            self.last_traces = [row for row in outputs if isinstance(row, AgentTraceEvent)]
            return [row for row in outputs if isinstance(row, OverlayCue)]
