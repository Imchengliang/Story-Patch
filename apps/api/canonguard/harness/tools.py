"""Closed set of tools the harness may execute (scene backend only).

Every capability the planner can reach lives here: a name, a Pydantic input
model, a deterministic implementation, and a short digest for the ledger. A tool
that is not registered simply cannot be called, which is what keeps this a
workable harness instead of an open-ended agent.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from canonguard.harness.store import ThreadStore
from canonguard.llm.gateway import LLMGateway
from canonguard.plot.aliases import AliasTable
from canonguard.plot.beats import expand_beats
from canonguard.plot.embedding import OllamaEmbedder
from canonguard.plot.raw_retrieval import build_scene_query, retrieve_scenes
from canonguard.plot.raw_suggest import generate_raw_suggestions
from canonguard.plot.scene_index import SceneHit, SceneIndex
from canonguard.plot.schemas import BeatSequence, PlotSuggestion, StuckPoint
from canonguard.plot.stuck_point import parse_stuck_point


class UnknownToolError(KeyError):
    pass


@dataclass
class ToolContext:
    gateway: LLMGateway
    aliases: AliasTable
    scene_index: SceneIndex | None = None
    embedder: OllamaEmbedder | None = None
    store: ThreadStore | None = None
    run_id: UUID | str | None = None
    thread_id: UUID | str | None = None
    story_facts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    value: Any = None
    digest: str = ""
    error: str = ""


class ParseStuckPointIn(BaseModel):
    story_state: str = Field(min_length=1)
    stuck_question: str = Field(min_length=1)
    genre: str = ""
    characters: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    desired_effect: str = ""


class UpdateStuckPointIn(BaseModel):
    stuck: StuckPoint
    changes: dict[str, Any]


class RetrieveScenesIn(BaseModel):
    stuck: StuckPoint
    top_k: int = Field(default=5, ge=1, le=10)
    candidate_k: int = Field(default=30, ge=1, le=200)
    mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    work_cap: int = Field(default=1, ge=1, le=10)


class SuggestFromScenesIn(BaseModel):
    stuck: StuckPoint
    scenes: list[SceneHit] = Field(min_length=1)


class ExpandBeatsIn(BaseModel):
    stuck: StuckPoint
    suggestion: PlotSuggestion
    scene_id: str = Field(min_length=1)


class RecordFeedbackIn(BaseModel):
    suggestion_ref: str = Field(min_length=1)
    decision: str = Field(pattern="^(accept|modify|reject)$")
    reason_code: str | None = None
    note: str | None = None


EDITABLE_STUCK_FIELDS = {
    "genre",
    "current_node",
    "stuck_question",
    "constraints",
    "desired_effect",
    "narrative_functions",
    "value_polarity",
}


def _digest_stuck(stuck: StuckPoint) -> str:
    functions = ", ".join(stuck.narrative_functions) or "-"
    return f"{len(stuck.characters)} characters · functions: {functions}"


def serialize_scenes(scenes: Sequence[SceneHit]) -> list[dict[str, Any]]:
    """Restorable form: the embedding vector stays out, the scene id stays in."""
    return [
        {
            "scene_id": hit.scene.scene_id,
            "work_title": hit.scene.work_title,
            "scene_heading": hit.scene.heading,
            "score": hit.score,
            "dense": hit.dense,
            "lexical": hit.lexical,
            "reasons": list(hit.reasons),
        }
        for hit in scenes
    ]


def _digest_scenes(scenes: Sequence[SceneHit]) -> str:
    return "; ".join(
        f"{hit.scene.work_title} | {hit.scene.heading} ({hit.score:.2f})" for hit in scenes
    )


def _digest_suggestions(suggestions: Sequence[PlotSuggestion]) -> str:
    referenced = sum(1 for item in suggestions if item.reference_quote)
    return f"{len(suggestions)} suggestions · {referenced} with verified quote"


def _digest_beats(sequence: BeatSequence) -> str:
    quoted = sum(1 for beat in sequence.beats if beat.reference_quote)
    return f"{len(sequence.beats)} beats · {quoted} with verified quote"


def _digest_feedback(value: str) -> str:
    return f"stored feedback {value}"


async def _parse_stuck_point(ctx: ToolContext, args: ParseStuckPointIn) -> StuckPoint:
    stuck, _ = await parse_stuck_point(
        ctx.gateway,
        story_state=args.story_state,
        stuck_question=args.stuck_question,
        genre=args.genre,
        characters=args.characters,
        constraints=args.constraints,
        desired_effect=args.desired_effect,
        alias_table=ctx.aliases,
    )
    return stuck


async def _update_stuck_point(ctx: ToolContext, args: UpdateStuckPointIn) -> StuckPoint:
    unknown = set(args.changes) - EDITABLE_STUCK_FIELDS
    if unknown:
        raise ValueError(f"fields are not editable: {', '.join(sorted(unknown))}")
    return StuckPoint.model_validate({**args.stuck.model_dump(), **args.changes})


async def _retrieve_scenes(ctx: ToolContext, args: RetrieveScenesIn) -> list[SceneHit]:
    if ctx.scene_index is None or ctx.embedder is None:
        raise RuntimeError("retrieve_scenes needs a scene index and an embedder")
    query = build_scene_query(args.stuck, ctx.aliases)
    vector = (await ctx.embedder.embed([query]))[0]
    return retrieve_scenes(
        ctx.scene_index,
        args.stuck,
        vector,
        ctx.aliases,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        mmr_lambda=args.mmr_lambda,
        work_cap=args.work_cap,
    )


async def _suggest_from_scenes(ctx: ToolContext, args: SuggestFromScenesIn) -> list[PlotSuggestion]:
    suggestions, _ = await generate_raw_suggestions(
        ctx.gateway, args.stuck, args.scenes, story_facts=ctx.story_facts
    )
    return suggestions


async def _expand_beats(ctx: ToolContext, args: ExpandBeatsIn) -> BeatSequence:
    if ctx.scene_index is None:
        raise RuntimeError("expand_beats needs a scene index")
    scene = ctx.scene_index.get(args.scene_id)
    if scene is None:
        raise ValueError(f"unknown scene: {args.scene_id}")
    sequence, _ = await expand_beats(ctx.gateway, args.stuck, args.suggestion, scene)
    return sequence


async def _record_feedback(ctx: ToolContext, args: RecordFeedbackIn) -> str:
    if ctx.store is None or ctx.run_id is None:
        raise RuntimeError("record_feedback needs a store and a run")
    feedback = ctx.store.record_feedback(
        suggestion_ref=args.suggestion_ref,
        decision=args.decision,
        thread_id=ctx.thread_id,
        run_id=ctx.run_id,
        reason_code=args.reason_code,
        note=args.note,
    )
    return str(feedback.id)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    run: Callable[[ToolContext, Any], Awaitable[Any]]
    digest: Callable[[Any], str]
    serialize: Callable[[Any], Any] | None = None
    idempotent: bool = True


TOOLS = (
    Tool(
        name="parse_stuck_point",
        description="Turn the writer's situation and question into a structured StuckPoint.",
        input_model=ParseStuckPointIn,
        run=_parse_stuck_point,
        digest=_digest_stuck,
    ),
    Tool(
        name="update_stuck_point",
        description="Apply writer edits to an existing StuckPoint.",
        input_model=UpdateStuckPointIn,
        run=_update_stuck_point,
        digest=_digest_stuck,
    ),
    Tool(
        name="retrieve_scenes",
        description="Retrieve raw precedent scenes by text similarity (no structural labels).",
        input_model=RetrieveScenesIn,
        run=_retrieve_scenes,
        digest=_digest_scenes,
        serialize=serialize_scenes,
    ),
    Tool(
        name="suggest_from_scenes",
        description="Generate 3-5 next-step suggestions from raw precedent scenes.",
        input_model=SuggestFromScenesIn,
        run=_suggest_from_scenes,
        digest=_digest_suggestions,
    ),
    Tool(
        name="expand_beats",
        description="Expand one accepted suggestion into a 2-3 beat sequence (still no prose).",
        input_model=ExpandBeatsIn,
        run=_expand_beats,
        digest=_digest_beats,
    ),
    Tool(
        name="record_feedback",
        description="Store an accept/modify/reject decision for one suggestion.",
        input_model=RecordFeedbackIn,
        run=_record_feedback,
        digest=_digest_feedback,
        idempotent=False,
    ),
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)
    return text if len(text) <= 500 else text[:500] + "…"


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(name) from exc

    def spec(self) -> list[dict[str, Any]]:
        """Machine-readable tool list handed to the planner."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "idempotent": tool.idempotent,
                "input_schema": tool.input_model.model_json_schema(),
            }
            for tool in self._tools.values()
        ]

    def serialize_output(self, name: str, value: Any) -> Any:
        tool = self._tools.get(name)
        return tool.serialize(value) if tool and tool.serialize else _jsonable(value)

    async def call(
        self,
        name: str,
        arguments: dict[str, Any] | str,
        ctx: ToolContext,
    ) -> ToolResult:
        """Run one tool and record it, including calls that never get that far."""
        payload = arguments if isinstance(arguments, dict) else {"raw": arguments}
        stored = self._begin(name, payload, ctx)
        result = await self._dispatch(name, arguments, ctx)
        self._finish(
            stored,
            result,
            self.serialize_output(name, result.value) if result.ok else None,
            ctx,
        )
        return result

    async def _dispatch(
        self, name: str, arguments: dict[str, Any] | str, ctx: ToolContext
    ) -> ToolResult:
        if isinstance(arguments, str):
            try:
                decoded = json.loads(arguments)
            except json.JSONDecodeError as exc:
                return ToolResult(name=name, ok=False, error=f"arguments are not JSON: {exc}")
            if not isinstance(decoded, dict):
                return ToolResult(name=name, ok=False, error="arguments must be a JSON object")
            arguments = decoded
        try:
            tool = self.get(name)
        except UnknownToolError:
            return ToolResult(name=name, ok=False, error=f"unknown tool: {name}")
        try:
            parsed = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                name=name,
                ok=False,
                error=f"invalid arguments for {name}: {exc.errors()[0]['msg']}",
            )
        except Exception as exc:  # noqa: BLE001 - report, never crash the run
            return ToolResult(name=name, ok=False, error=f"invalid arguments for {name}: {exc}")
        try:
            value = await tool.run(ctx, parsed)
        except Exception as exc:  # noqa: BLE001 - the run must stay accountable
            return ToolResult(name=name, ok=False, error=f"{name} failed: {exc}")
        return ToolResult(name=name, ok=True, value=value, digest=tool.digest(value))

    def _begin(self, name: str, arguments: dict[str, Any], ctx: ToolContext) -> Any:
        if ctx.store is None or ctx.run_id is None:
            return None
        return ctx.store.record_tool_call(ctx.run_id, name, input=_jsonable(arguments))

    def _finish(self, stored: Any, result: ToolResult, output: Any, ctx: ToolContext) -> None:
        if ctx.store is None or stored is None:
            return
        ctx.store.finish_tool_call(
            stored.id,
            status="succeeded" if result.ok else "failed",
            output_digest=result.digest,
            output=output,
            error=result.error or None,
        )


default_registry = ToolRegistry(TOOLS)
