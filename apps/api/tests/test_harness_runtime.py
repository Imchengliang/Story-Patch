import json
from typing import Any

import pytest

from canonguard.db.session import SessionLocal
from canonguard.harness.planner import Plan, PlanStep, default_plan
from canonguard.harness.runtime import TurnInput, run_turn
from canonguard.harness.store import ThreadStore
from canonguard.harness.tools import ToolContext, default_registry
from canonguard.llm.gateway import RawCompletion, RoleConfig, StructuredGateway
from canonguard.plot.aliases import parse_alias_table
from canonguard.plot.scene_index import SceneIndex, SceneUnit
from canonguard.runs.ledger import RunLedger

STUCK_DRAFT = {
    "genre": "Drama",
    "characters": [{"name": "Baoyu", "function": "protagonist"}],
    "current_node": "Baoyu holds the handkerchief.",
    "stuck_question": "How do they move on without reconciling?",
    "constraints": ["No coincidences"],
    "desired_effect": "Advance the relationship",
    "narrative_functions": ["relationship_turn"],
    "value_polarity": "mixed",
}

SUGGESTIONS = {
    "suggestions": [
        {
            "precedent_index": index,
            "next_node": f"Beat {index}.",
            "character_behavior_logic": "He acts instead of explaining.",
            "emotional_tone": "restrained",
            "transfer_rationale": "Same negotiation structure.",
            "reference_quote": f"q{index}",
            "fit_score": 0.8,
            "novelty_score": 0.6,
        }
        for index in (1, 2, 1)
    ]
}


class RoleCompleter:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads

    async def __call__(
        self, model: str, messages: list[dict[str, str]], config: RoleConfig
    ) -> RawCompletion:
        return RawCompletion(content=json.dumps(self.payloads[model.split("/")[-1]]), model=model)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


def _scene_index() -> SceneIndex:
    units = [
        SceneUnit(
            scene_id=f"w:{index}",
            work_id=f"w{index}",
            work_title=f"Work {index}",
            language="zh",
            genre="Drama",
            scene_no=index,
            heading=f"SC {index}",
            text=f"q{index} 宝玉把帕子塞进袖子里，没有说话。",
            characters=("Baoyu",),
        )
        for index in (1, 2)
    ]
    return SceneIndex(units, [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])


def _context(run_id: str | None = None) -> ToolContext:
    run = run_id or str(RunLedger(SessionLocal).create_run("plot_turn").id)
    return ToolContext(
        gateway=StructuredGateway(
            roles={role: RoleConfig(model=f"fake/{role}") for role in ("extractor", "writer")},
            completer=RoleCompleter({"extractor": STUCK_DRAFT, "writer": SUGGESTIONS}),
        ),
        aliases=parse_alias_table({}),
        scene_index=_scene_index(),
        embedder=FakeEmbedder(),
        store=ThreadStore(SessionLocal),
        run_id=run,
    )


TURN = TurnInput(
    story_state="Baoyu holds a handkerchief.",
    stuck_question="How do they move on without reconciling?",
    genre="Drama",
    characters=["Baoyu", "Daiyu"],
)


async def test_default_pipeline_produces_a_full_turn() -> None:
    ctx = _context()
    outcome = await run_turn(default_registry, ctx, TURN)

    assert outcome.ok is True
    assert [step.tool for step in outcome.steps] == list(default_plan().tools())
    assert outcome.state.stuck is not None
    assert len(outcome.state.scenes) == 2
    assert len(outcome.state.suggestions) == 3


async def test_events_are_emitted_in_order() -> None:
    outcome = await run_turn(default_registry, _context(), TURN)
    names = [event for event, _ in outcome.events]

    assert names[0] == "plan"
    assert names[-1] == "done"
    assert names.index("stuck_point") < names.index("precedents")
    assert names.count("suggestion") == 3
    assert names.count("tool_result") == 3


async def test_every_step_is_written_to_the_tool_ledger() -> None:
    ctx = _context()
    outcome = await run_turn(default_registry, ctx, TURN)
    calls = ctx.store.list_tool_calls(ctx.run_id)  # type: ignore[union-attr]

    assert [call.name for call in calls] == list(default_plan().tools())
    assert all(call.status == "succeeded" for call in calls)
    assert calls[0].output_digest == outcome.steps[0].digest
    assert "Work 1" in calls[1].output_digest


async def test_a_failing_step_degrades_to_the_remaining_pipeline() -> None:
    plan = Plan(
        steps=[
            PlanStep(tool="update_stuck_point", args={"changes": {"story_state": "重写正文"}}),
            PlanStep(tool="parse_stuck_point"),
            PlanStep(tool="retrieve_scenes"),
            PlanStep(tool="suggest_from_scenes"),
        ],
        note="planner",
    )
    outcome = await run_turn(default_registry, _context(), TURN, plan)

    assert outcome.steps[0].ok is False
    assert outcome.used_fallback is True
    assert outcome.ok is True
    assert [step.tool for step in outcome.steps[1:]] == list(default_plan().tools())


async def test_a_failing_fallback_step_reports_failure() -> None:
    ctx = _context()
    ctx.scene_index = None
    outcome = await run_turn(default_registry, ctx, TURN)

    assert outcome.ok is False
    assert outcome.used_fallback is True
    assert "scene index" in outcome.error


async def test_plans_beyond_the_llm_budget_are_replaced() -> None:
    plan = Plan(steps=[PlanStep(tool="suggest_from_scenes") for _ in range(9)], note="planner")
    outcome = await run_turn(default_registry, _context(), TURN, plan)

    assert [step.tool for step in outcome.steps[:3]] == list(default_plan().tools())


@pytest.mark.parametrize("tool", ["retrieve_scenes", "suggest_from_scenes"])
async def test_registry_rejects_missing_required_arguments(tool: str) -> None:
    result = await default_registry.call(tool, {}, _context())
    assert result.ok is False
    assert "invalid arguments" in result.error
