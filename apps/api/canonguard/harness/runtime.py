"""Turn execution: thread tool outputs together, emit events, degrade safely."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from canonguard.harness.budget import Budget, Usage, exceeded
from canonguard.harness.planner import (
    MAX_PLAN_LLM_CALLS,
    PIPELINE,
    Plan,
    PlanStep,
    default_plan,
)
from canonguard.harness.tools import ToolContext, ToolRegistry
from canonguard.plot.scene_index import SceneHit
from canonguard.plot.schemas import PlotSuggestion, StuckPoint

LLM_TOOLS = frozenset({"parse_stuck_point", "suggest_from_scenes"})


@dataclass(frozen=True)
class TurnInput:
    story_state: str
    stuck_question: str
    genre: str = ""
    characters: Sequence[str] = ()
    constraints: Sequence[str] = ()
    desired_effect: str = ""


@dataclass
class RunState:
    stuck: StuckPoint | None = None
    scenes: list[SceneHit] = field(default_factory=list)
    suggestions: list[PlotSuggestion] = field(default_factory=list)

    def produced(self) -> set[str]:
        done: set[str] = set()
        if self.stuck is not None:
            done.add("parse_stuck_point")
        if self.scenes:
            done.add("retrieve_scenes")
        if self.suggestions:
            done.add("suggest_from_scenes")
        return done


@dataclass
class StepOutcome:
    tool: str
    ok: bool
    digest: str = ""
    error: str = ""


@dataclass
class TurnOutcome:
    plan: Plan
    steps: list[StepOutcome] = field(default_factory=list)
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    state: RunState = field(default_factory=RunState)
    used_fallback: bool = False
    ok: bool = True
    error: str = ""


def bind_arguments(
    step: PlanStep,
    turn: TurnInput,
    state: RunState,
) -> dict[str, Any]:
    """Merge the planner's overrides with whatever earlier steps already produced."""
    args: dict[str, Any] = dict(step.args)
    if step.tool == "parse_stuck_point":
        args.setdefault("story_state", turn.story_state)
        args.setdefault("stuck_question", turn.stuck_question)
        args.setdefault("genre", turn.genre)
        args.setdefault("characters", list(turn.characters))
        args.setdefault("constraints", list(turn.constraints))
        args.setdefault("desired_effect", turn.desired_effect)
    if state.stuck is not None:
        args.setdefault("stuck", state.stuck)
    if step.tool == "suggest_from_scenes" and state.scenes:
        args.setdefault("scenes", state.scenes)
    return args


def _apply(state: RunState, tool: str, value: Any) -> list[tuple[str, dict[str, Any]]]:
    if tool == "parse_stuck_point" and isinstance(value, StuckPoint):
        state.stuck = value
        return [("stuck_point", value.model_dump(mode="json"))]
    if tool == "update_stuck_point" and isinstance(value, StuckPoint):
        state.stuck = value
        return [("stuck_point", value.model_dump(mode="json"))]
    if tool == "retrieve_scenes" and isinstance(value, list):
        state.scenes = value
        return [
            (
                "precedents",
                {
                    "kind": "scene",
                    "hits": [
                        {
                            "work_title": hit.scene.work_title,
                            "scene_heading": hit.scene.heading,
                            "score": round(hit.score, 4),
                            "reasons": list(hit.reasons),
                        }
                        for hit in value
                    ],
                },
            )
        ]
    if tool == "suggest_from_scenes" and isinstance(value, list):
        state.suggestions = value
        return [("suggestion", item.model_dump(mode="json")) for item in value]
    return []


def _usage(ctx: ToolContext) -> Usage | None:
    if ctx.store is None or ctx.run_id is None:
        return None
    return Usage.from_row(ctx.store.usage_for_run(ctx.run_id))


def _enforce_budget(plan: Plan) -> Plan:
    calls = sum(1 for step in plan.steps if step.tool in LLM_TOOLS)
    return plan if calls <= MAX_PLAN_LLM_CALLS else default_plan()


async def stream_turn(
    registry: ToolRegistry,
    ctx: ToolContext,
    turn: TurnInput,
    plan: Plan | None = None,
    state: RunState | None = None,
    budget: Budget | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Run one writer turn, yielding SSE-ready events.

    Pass a ``state`` to keep the accumulated results after the stream ends.
    """
    active = _enforce_budget(plan or default_plan())
    live = state if state is not None else RunState()
    used_fallback = False
    queue: list[PlanStep] = list(active.steps)

    yield (
        "plan",
        {
            "steps": [{"tool": step.tool, "reason": step.reason} for step in queue],
            "note": active.note,
        },
    )

    while queue:
        step = queue.pop(0)
        result = await registry.call(step.tool, bind_arguments(step, turn, live), ctx)
        yield (
            "tool_result",
            {
                "tool": step.tool,
                "status": "succeeded" if result.ok else "failed",
                "digest": result.digest,
                "error": result.error,
            },
        )
        if not result.ok:
            remaining = [name for name in PIPELINE if name not in live.produced()]
            if not used_fallback and remaining:
                used_fallback = True
                yield "fallback", {"reason": result.error, "tools": remaining}
                queue = [PlanStep(tool=name, reason="fallback") for name in remaining]
                continue
            yield "done", {"ok": False, "error": result.error, "used_fallback": used_fallback}
            return
        for event in _apply(live, step.tool, result.value):
            yield event
        if budget is not None:
            usage = _usage(ctx)
            if usage is not None:
                yield "budget", {**usage.as_dict(), "limits": _limits(budget)}
                reason = exceeded(usage, budget)
                if reason:
                    yield (
                        "done",
                        {
                            "ok": False,
                            "error": reason,
                            "used_fallback": used_fallback,
                            "usage": usage.as_dict(),
                        },
                    )
                    return

    usage = _usage(ctx) if budget is not None else None
    yield (
        "done",
        {
            "ok": True,
            "error": "",
            "used_fallback": used_fallback,
            "usage": usage.as_dict() if usage else None,
        },
    )


def _limits(budget: Budget) -> dict[str, Any]:
    return {"max_tokens": budget.max_tokens, "max_cost_usd": budget.max_cost_usd}


async def run_turn(
    registry: ToolRegistry,
    ctx: ToolContext,
    turn: TurnInput,
    plan: Plan | None = None,
    budget: Budget | None = None,
) -> TurnOutcome:
    """Collect :func:`stream_turn` into one object (CLI, tests, batch evaluation)."""
    state = RunState()
    outcome = TurnOutcome(plan=plan or default_plan(), state=state)
    async for event, data in stream_turn(registry, ctx, turn, plan, state, budget):
        outcome.events.append((event, data))
        if event == "tool_result":
            outcome.steps.append(
                StepOutcome(
                    tool=str(data["tool"]),
                    ok=data["status"] == "succeeded",
                    digest=str(data.get("digest", "")),
                    error=str(data.get("error", "")),
                )
            )
        elif event == "fallback":
            outcome.used_fallback = True
        elif event == "done":
            outcome.ok = bool(data["ok"])
            outcome.error = str(data.get("error", ""))
    return outcome
