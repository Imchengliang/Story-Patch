"""Resume and replay, built on the ledger rather than on a graph framework.

The ledger already records every tool call with its input and serialised output,
so "continue this run" and "run this again and tell me if it drifts" are reads
plus a loop. That keeps the prompts and model choices auditable without
inventing a second source of truth.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from canonguard.db.models import ToolCall
from canonguard.harness.planner import PIPELINE, Plan, PlanStep
from canonguard.harness.runtime import RunState, TurnInput, bind_arguments, stream_turn
from canonguard.harness.tools import ToolContext, ToolRegistry
from canonguard.plot.scene_index import SceneHit, SceneIndex
from canonguard.plot.schemas import PlotSuggestion, StuckPoint

EXACT_TOOLS = frozenset({"parse_stuck_point", "update_stuck_point", "retrieve_scenes"})


@dataclass
class Restored:
    state: RunState = field(default_factory=RunState)
    completed: list[str] = field(default_factory=list)
    calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ReplayCheck:
    tool: str
    equal: bool
    detail: str = ""
    comparable: bool = True


@dataclass
class ReplayReport:
    source_run_id: str
    new_run_id: str
    ok: bool = True
    checks: list[ReplayCheck] = field(default_factory=list)
    error: str = ""


def restore_state(calls: Sequence[ToolCall], index: SceneIndex) -> Restored:
    """Rebuild a run's state from its ledger rows."""
    state = RunState()
    completed: list[str] = []
    for call in calls:
        if call.status != "succeeded" or call.output is None:
            continue
        output = call.output
        if call.name in {"parse_stuck_point", "update_stuck_point"}:
            state.stuck = StuckPoint.model_validate(output)
        elif call.name == "retrieve_scenes" and isinstance(output, list):
            hits: list[SceneHit] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                scene = index.get(str(item.get("scene_id", "")))
                if scene is None:
                    continue
                hits.append(
                    SceneHit(
                        scene=scene,
                        score=float(item.get("score", 0.0)),
                        dense=float(item.get("dense", 0.0)),
                        lexical=float(item.get("lexical", 0.0)),
                        reasons=tuple(item.get("reasons", ())),
                    )
                )
            state.scenes = hits
        elif call.name == "suggest_from_scenes" and isinstance(output, list):
            state.suggestions = [PlotSuggestion.model_validate(item) for item in output]
        completed.append(call.name)
    return Restored(state=state, completed=completed, calls=list(calls))


def remaining_pipeline(completed: Sequence[str]) -> list[str]:
    return [name for name in PIPELINE if name not in set(completed)]


async def stream_resume(
    registry: ToolRegistry,
    ctx: ToolContext,
    turn: TurnInput,
    source_run_id: str,
    budget: Any | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Continue a run that died halfway: reuse its outputs, execute only what is missing."""
    if ctx.store is None or ctx.scene_index is None:
        raise RuntimeError("resume needs a store and a scene index")
    calls = ctx.store.list_tool_calls(source_run_id)
    restored = restore_state(calls, ctx.scene_index)
    missing = remaining_pipeline(restored.completed)
    if not missing:
        yield (
            "done",
            {
                "ok": True,
                "error": "",
                "used_fallback": False,
                "resumed_from": source_run_id,
                "skipped": list(restored.completed),
            },
        )
        return
    plan = Plan(
        steps=[PlanStep(tool=name, reason="resumed from ledger") for name in missing],
        note="resume",
    )
    async for event, data in stream_turn(registry, ctx, turn, plan, restored.state, budget):
        yield event, {**data, "resumed_from": source_run_id}


def _parse_signature(payload: Any) -> Any:
    """Structural fields only: free-text wording may vary even at temperature 0.

    Genre, narrative functions, value polarity, character functions and
    constraints are what retrieval and generation actually key on; ``current_node``
    or ``desired_effect`` wording is not part of the replay contract.
    """
    if not isinstance(payload, dict):
        return payload
    characters = payload.get("characters") or []
    character_set = sorted(
        (str(item.get("name", "")), str(item.get("function", "")))
        for item in characters
        if isinstance(item, dict)
    )
    return (
        str(payload.get("genre", "")),
        tuple(payload.get("narrative_functions") or []),
        str(payload.get("value_polarity", "")),
        tuple(character_set),
        tuple(sorted(str(item) for item in payload.get("constraints") or [])),
    )


def compare_outputs(tool: str, original: Any, replayed: Any) -> ReplayCheck:
    if tool == "retrieve_scenes":
        before = [item.get("scene_id") for item in original or [] if isinstance(item, dict)]
        after = [item.get("scene_id") for item in replayed or [] if isinstance(item, dict)]
        return ReplayCheck(tool, before == after, f"{before} vs {after}")
    if tool == "parse_stuck_point":
        before = _parse_signature(original)
        after = _parse_signature(replayed)
        return ReplayCheck(tool, before == after, "" if before == after else f"{before} vs {after}")
    if tool == "suggest_from_scenes":
        before = original or []
        after = replayed or []
        same_count = len(before) == len(after)
        sources = {item.get("corpus_reference") for item in before} == {
            item.get("corpus_reference") for item in after
        }
        # The writer runs at temperature 0.6: count and precedent set are the contract,
        # which evidence line it happens to quote is not.
        quotes = {item.get("reference_quote") for item in before} == {
            item.get("reference_quote") for item in after
        }
        return ReplayCheck(
            tool,
            same_count and sources,
            f"count {len(before)}/{len(after)} · precedents match={sources} · "
            f"quotes identical={quotes}",
        )
    if tool in EXACT_TOOLS:
        return ReplayCheck(tool, original == replayed, "" if original == replayed else "differs")
    return ReplayCheck(tool, bool(replayed is not None), "presence only")


async def replay_run(
    registry: ToolRegistry,
    ctx: ToolContext,
    turn: TurnInput,
    source_run_id: str,
    new_run_id: str,
    seed: RunState | None = None,
) -> ReplayReport:
    """Re-execute a recorded run from scratch and compare it step by step.

    ``seed`` carries what the original run was handed rather than produced -
    typically the thread's stored stuck point for a follow-up turn.
    """
    if ctx.store is None or ctx.scene_index is None:
        raise RuntimeError("replay needs a store and a scene index")
    original_calls = [call for call in ctx.store.list_tool_calls(source_run_id) if call.name]
    if not original_calls:
        return ReplayReport(source_run_id, new_run_id, ok=False, error="source run has no steps")
    plan = Plan(
        steps=[PlanStep(tool=call.name, reason="replay") for call in original_calls],
        note="replay",
    )

    ctx.run_id = new_run_id
    state = seed if seed is not None else RunState()
    report = ReplayReport(source_run_id, new_run_id)
    for call, step in zip(original_calls, plan.steps, strict=True):
        result = await registry.call(step.tool, bind_arguments(step, turn, state), ctx)
        if not result.ok:
            report.ok = False
            report.error = f"{step.tool} failed during replay: {result.error}"
            return report
        replayed = registry.serialize_output(step.tool, result.value)
        check = compare_outputs(step.tool, call.output, replayed)
        if call.output is None:
            check = ReplayCheck(
                step.tool, True, "source run predates output capture", comparable=False
            )
        report.checks.append(check)
        _absorb(state, step.tool, result.value)

    report.ok = all(check.equal for check in report.checks if check.comparable)
    return report


def _absorb(state: RunState, tool: str, value: Any) -> None:
    if isinstance(value, StuckPoint):
        state.stuck = value
    elif isinstance(value, list) and value and isinstance(value[0], SceneHit):
        state.scenes = value
    elif isinstance(value, list) and value and isinstance(value[0], PlotSuggestion):
        state.suggestions = value
